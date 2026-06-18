from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Certificado, Empresa
from app.schemas import CertificadoOut, EmpresaCreate, EmpresaOut, EmpresaUpdate
from app.services.crypto import encrypt_bytes, decrypt_bytes

from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12

router = APIRouter(prefix="/empresas", tags=["empresas"])


@router.delete("/{empresa_id}/certificados")
def deletar_certificados(empresa_id: str, db: Session = Depends(get_db)):
    """Remove todos os certificados da empresa para permitir re-upload limpo."""
    n = db.query(Certificado).filter_by(empresa_id=empresa_id).delete()
    db.commit()
    return {"deletados": n}


@router.get("/{empresa_id}/certificado/diagnostico")
def diagnostico_certificado(empresa_id: str, db: Session = Depends(get_db)):
    """Diagnóstico: verifica se o certificado pode ser descriptografado."""
    cert = db.query(Certificado).filter_by(empresa_id=empresa_id, status="ativo").order_by(Certificado.valido_ate.desc()).first()
    if not cert:
        return {"ok": False, "erro": "Nenhum certificado ativo encontrado"}
    import hashlib
    try:
        key = settings.vault_master_key_bytes
        key_len = len(key)
        key_hash = hashlib.sha256(key).hexdigest()[:16]
    except Exception as e:
        return {"ok": False, "erro": f"VAULT_MASTER_KEY inválida: {e}"}

    # Criptografar e descriptografar um teste para verificar a chave
    test_plain = b"test"
    test_enc = encrypt_bytes(test_plain, key)
    try:
        assert decrypt_bytes(test_enc, key) == test_plain
        roundtrip_ok = True
    except Exception:
        roundtrip_ok = False

    try:
        pfx = decrypt_bytes(cert.pfx_cifrado, key)
        senha = decrypt_bytes(cert.senha_cifrada, key).decode()
        from cryptography.hazmat.primitives.serialization import pkcs12 as pkcs12_mod
        pk, c, _ = pkcs12_mod.load_key_and_certificates(pfx, senha.encode())
        return {"ok": True, "key_len": key_len, "key_hash": key_hash, "roundtrip_ok": roundtrip_ok, "fingerprint": cert.fingerprint, "valido_ate": str(cert.valido_ate), "subject": str(c.subject)}
    except Exception as e:
        return {"ok": False, "key_len": key_len, "key_hash": key_hash, "roundtrip_ok": roundtrip_ok, "fingerprint": cert.fingerprint, "erro": repr(e)}


@router.get("", response_model=List[EmpresaOut])
def listar_empresas(organizacao_id: str = None, db: Session = Depends(get_db)):
    q = db.query(Empresa)
    if organizacao_id:
        q = q.filter_by(organizacao_id=organizacao_id)
    return q.order_by(Empresa.criado_em.desc()).all()


@router.post("", response_model=EmpresaOut, status_code=201)
def criar_empresa(body: EmpresaCreate, db: Session = Depends(get_db)):
    empresa = Empresa(**body.model_dump())
    db.add(empresa)
    db.commit()
    db.refresh(empresa)
    return empresa


@router.get("/{empresa_id}", response_model=EmpresaOut)
def buscar_empresa(empresa_id: str, db: Session = Depends(get_db)):
    empresa = db.get(Empresa, empresa_id)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    return empresa


@router.patch("/{empresa_id}", response_model=EmpresaOut)
def atualizar_empresa(empresa_id: str, body: EmpresaUpdate, db: Session = Depends(get_db)):
    empresa = db.get(Empresa, empresa_id)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(empresa, field, value)
    db.commit()
    db.refresh(empresa)
    return empresa


@router.post("/{empresa_id}/certificado", response_model=CertificadoOut, status_code=201)
def upload_certificado(
    empresa_id: str,
    arquivo: UploadFile = File(...),
    senha: str = Form(...),
    db: Session = Depends(get_db),
):
    empresa = db.get(Empresa, empresa_id)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    pfx_bytes = arquivo.file.read()
    senha_bytes = senha.encode()

    try:
        pk, cert, _ = pkcs12.load_key_and_certificates(pfx_bytes, senha_bytes)
    except Exception:
        raise HTTPException(status_code=422, detail="Certificado inválido ou senha incorreta")

    from cryptography.hazmat.primitives import hashes
    from datetime import timezone as _tz
    fingerprint = cert.fingerprint(hashes.SHA256()).hex()
    # not_valid_before_utc foi adicionado na cryptography 42 — fallback para versões anteriores
    if hasattr(cert, "not_valid_before_utc"):
        valido_de = cert.not_valid_before_utc
        valido_ate = cert.not_valid_after_utc
    else:
        valido_de = cert.not_valid_before.replace(tzinfo=_tz.utc)
        valido_ate = cert.not_valid_after.replace(tzinfo=_tz.utc)

    try:
        master_key = settings.vault_master_key_bytes
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"VAULT_MASTER_KEY inválida: {e}")

    try:
        pfx_enc = encrypt_bytes(pfx_bytes, master_key)
        senha_enc = encrypt_bytes(senha_bytes, master_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na criptografia: {e}")

    certificado = Certificado(
        empresa_id=empresa_id,
        pfx_cifrado=pfx_enc,
        senha_cifrada=senha_enc,
        fingerprint=fingerprint,
        valido_de=valido_de,
        valido_ate=valido_ate,
    )
    db.add(certificado)

    # Reativar estados de distribuição travados em cert_invalido
    from app.models import DistribuicaoEstado
    db.query(DistribuicaoEstado).filter_by(
        empresa_id=empresa_id, status="cert_invalido"
    ).update({"status": "ativo"})

    db.commit()
    db.refresh(certificado)
    return certificado

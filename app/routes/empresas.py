from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Certificado, Empresa
from app.schemas import CertificadoOut, EmpresaCreate, EmpresaOut
from app.services.crypto import encrypt_bytes

from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12

router = APIRouter(prefix="/empresas", tags=["empresas"])


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

    master_key = settings.vault_master_key_bytes
    certificado = Certificado(
        empresa_id=empresa_id,
        pfx_cifrado=encrypt_bytes(pfx_bytes, master_key),
        senha_cifrada=encrypt_bytes(senha_bytes, master_key),
        fingerprint=fingerprint,
        valido_de=valido_de,
        valido_ate=valido_ate,
    )
    db.add(certificado)
    db.commit()
    db.refresh(certificado)
    return certificado

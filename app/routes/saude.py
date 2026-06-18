import socket as _socket

from fastapi import APIRouter
from app.config import settings

router = APIRouter(tags=["saude"])


@router.get("/health")
def health():
    return {"status": "ok", "env": settings.app_env}


@router.get("/debug/sefaz-tcp")
def debug_sefaz_tcp():
    """Testa conectividade TCP direta ao IP SEFAZ (diagnóstico Railway)."""
    from app.services import sefaz_client as _sc  # garante que o patch está ativo
    ip = "200.198.239.181"
    port = 443
    results = {}
    for host in [ip, "www1.nfe.fazenda.gov.br"]:
        try:
            s = _socket.create_connection((host, port), timeout=10)
            s.close()
            results[host] = "ok"
        except Exception as e:
            results[host] = str(e)
    patch_active = _socket.getaddrinfo is not _sc._orig_getaddrinfo
    return {"patch_active": patch_active, "results": results, "tp_amb": settings.tp_amb, "endpoint": settings.nfe_endpoint}


@router.get("/debug/sefaz-envelope/{empresa_id}")
def debug_sefaz_envelope(empresa_id: str):
    """Mostra o envelope SOAP exato + faz o POST real e retorna request/response crus."""
    import httpx
    from app.db import SessionLocal
    from app.models import Certificado, Empresa
    from app.services import sefaz_client as sc
    from app.services.crypto import decrypt_bytes

    db = SessionLocal()
    try:
        empresa = db.get(Empresa, empresa_id)
        cert = (
            db.query(Certificado)
            .filter_by(empresa_id=empresa_id, status="ativo")
            .order_by(Certificado.valido_ate.desc())
            .first()
        )
        if not empresa or not cert:
            return {"erro": "empresa ou certificado não encontrado"}

        key = settings.vault_master_key_bytes
        pfx = decrypt_bytes(cert.pfx_cifrado, key)
        senha = decrypt_bytes(cert.senha_cifrada, key).decode()

        uf_code = sc.uf_to_code(empresa.uf or "SP")
        inner = "<distNSU><ultNSU>000000000000000</ultNSU></distNSU>"
        envelope = sc._soap_envelope(settings.tp_amb, uf_code, empresa.cnpj, inner, "nfe")

        op_tag, _ = sc._DIST_ROOT["nfe"]
        wsdl_ns = sc._WSDL_NS["nfe"]
        action = f"{wsdl_ns}/{op_tag}"
        content_type = f'application/soap+xml; charset=utf-8; action="{action}"'

        cert_pem, key_pem = sc._pfx_to_pem(pfx, senha)
        ssl_ctx = sc._build_ssl_context(cert_pem, key_pem)

        try:
            with httpx.Client(verify=ssl_ctx, timeout=30) as client:
                resp = client.post(
                    settings.nfe_endpoint,
                    content=envelope.encode("utf-8"),
                    headers={"Content-Type": content_type},
                )
            resp_info = {"status": resp.status_code, "body": resp.text[:3000]}
        except Exception as e:
            resp_info = {"erro": repr(e)}

        return {
            "envelope": envelope,
            "content_type": content_type,
            "endpoint": settings.nfe_endpoint,
            "cnpj": empresa.cnpj,
            "uf": empresa.uf,
            "uf_code": uf_code,
            "tp_amb": settings.tp_amb,
            "response": resp_info,
        }
    finally:
        db.close()

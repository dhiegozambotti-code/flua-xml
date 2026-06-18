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

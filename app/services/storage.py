"""Armazenamento local de XMLs (Phase 1).

Em fases futuras, será substituído/complementado por S3/R2.
storage_key retornado é o caminho relativo a settings.storage_local_dir.
"""

import os

from app.config import settings


def save_xml(empresa_id: str, modelo: str, chave: str, xml_bytes: bytes) -> str:
    """Salva o XML e retorna o storage_key (caminho relativo)."""
    prefix = chave[:4] if chave and len(chave) >= 4 else "0000"
    rel_path = os.path.join(modelo, empresa_id, prefix, f"{chave}.xml")
    full_path = os.path.join(settings.storage_local_dir, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "wb") as f:
        f.write(xml_bytes)
    return rel_path


def load_xml(storage_key: str) -> bytes:
    full_path = os.path.join(settings.storage_local_dir, storage_key)
    with open(full_path, "rb") as f:
        return f.read()

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class EmpresaCreate(BaseModel):
    organizacao_id: str
    cnpj: str
    razao_social: Optional[str] = None
    uf: Optional[str] = None
    regime: Optional[str] = None


class EmpresaOut(BaseModel):
    id: str
    organizacao_id: str
    cnpj: str
    razao_social: Optional[str]
    uf: Optional[str]
    regime: Optional[str]
    ativo: bool
    criado_em: datetime

    model_config = {"from_attributes": True}


class CertificadoOut(BaseModel):
    id: str
    empresa_id: str
    tipo: str
    fingerprint: Optional[str]
    valido_de: Optional[datetime]
    valido_ate: Optional[datetime]
    status: str
    criado_em: datetime

    model_config = {"from_attributes": True}

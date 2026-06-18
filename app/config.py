from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://flua:flua@localhost:5432/flua_xml"
    vault_master_key: str = "0" * 64  # hex 32 bytes — obrigatório em prod
    app_env: str = "local"

    @property
    def database_url_psycopg(self) -> str:
        """Converte URL do Railway (postgresql://) para o driver psycopg3."""
        url = self.database_url
        if url.startswith("postgresql://") and "+psycopg" not in url:
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url
    storage_bucket: str = "flua-xml-docs"
    storage_local_dir: str = "storage"  # pasta local para XMLs (Phase 1)

    # SEFAZ — endpoints configuráveis (nunca hardcodados)
    nfe_endpoint_prod: str = "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
    nfe_endpoint_homolog: str = "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
    tp_amb: str = "2"  # 1=produção | 2=homologação — default seguro

    # SEFAZ — CT-e (CTeDistribuicaoDFe — NT 2015.002)
    cte_endpoint_prod: str = "https://cte.fazenda.gov.br/CTeDistribuicaoDFe/CTeDistribuicaoDFe.asmx"
    cte_endpoint_homolog: str = "https://homologacao.cte.fazenda.gov.br/CTeDistribuicaoDFe/CTeDistribuicaoDFe.asmx"

    # SEFAZ — MDF-e (MdFeDistribuicaoDFe)
    mdfe_endpoint_prod: str = "https://mdfe.fazenda.gov.br/MdFeDistribuicaoDFe/MdFeDistribuicaoDFe.asmx"
    mdfe_endpoint_homolog: str = "https://homologacao.mdfe.fazenda.gov.br/MdFeDistribuicaoDFe/MdFeDistribuicaoDFe.asmx"

    # SEFAZ — evento (Manifestação do Destinatário)
    nfe_evento_endpoint_prod: str = "https://www.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx"
    nfe_evento_endpoint_homolog: str = "https://homologacao.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx"

    # Manifestação automática
    auto_manifestacao_habilitado: bool = True
    auto_manifestacao_tipo: str = "210210"  # Ciência da Operação (padrão)

    # Orquestrador
    polling_interval_seconds: int = 30    # intervalo entre varreduras completas
    polling_lock_ttl_seconds: int = 300   # TTL do lock por empresa×modelo
    polling_max_retries: int = 3          # tentativas em caso de timeout/erro
    polling_enabled: bool = True          # desabilitar em testes

    @property
    def vault_master_key_bytes(self) -> bytes:
        return bytes.fromhex(self.vault_master_key.strip())

    @property
    def nfe_endpoint(self) -> str:
        return self.nfe_endpoint_prod if self.tp_amb == "1" else self.nfe_endpoint_homolog

    @property
    def nfe_evento_endpoint(self) -> str:
        return self.nfe_evento_endpoint_prod if self.tp_amb == "1" else self.nfe_evento_endpoint_homolog

    @property
    def cte_endpoint(self) -> str:
        return self.cte_endpoint_prod if self.tp_amb == "1" else self.cte_endpoint_homolog

    @property
    def mdfe_endpoint(self) -> str:
        return self.mdfe_endpoint_prod if self.tp_amb == "1" else self.mdfe_endpoint_homolog


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

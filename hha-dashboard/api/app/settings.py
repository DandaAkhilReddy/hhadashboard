from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: str = Field(default="dev")
    log_level: str = Field(default="INFO")

    database_url: str = Field(
        default="postgresql+asyncpg://hha:hha@localhost:5432/hha_dashboard"
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg://hha:hha@localhost:5432/hha_dashboard"
    )

    azure_tenant_id: str = ""
    azure_api_client_id: str = ""
    azure_api_scope: str = ""

    entra_group_admin: str = ""
    entra_group_exec: str = ""
    entra_group_comp_viewer: str = ""
    entra_group_owner_ops: str = ""
    entra_group_owner_finance: str = ""
    entra_group_owner_clinical: str = ""
    entra_group_owner_hr: str = ""

    # ---------- Blob Storage (Session 3) ----------
    # Dev: Azurite → connection string below. Prod: Managed Identity → only account_url needed.
    azure_storage_account_url: str = "http://localhost:10000/devstoreaccount1"
    azure_storage_connection_string: str = ""  # only set in dev; prod uses MI
    azure_storage_uploads_container: str = "uploads"

    # ---------- Azure Document Intelligence ----------
    azure_doc_intelligence_endpoint: str = ""
    azure_doc_intelligence_api_key: str = ""

    # ---------- Upload limits ----------
    upload_max_bytes: int = 25 * 1024 * 1024  # 25 MB
    upload_allowed_mime_types: tuple[str, ...] = (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
        "application/vnd.ms-excel",  # .xls
        "text/csv",
    )


settings = Settings()

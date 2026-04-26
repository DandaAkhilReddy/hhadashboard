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

    @property
    def entra_configured(self) -> bool:
        """Real JWT verification is only attempted when both the tenant and
        API audience are set. Otherwise we fall through to the dev stub
        (`Authorization: Dev <role>`). Useful for local dev + tests where
        full Azure setup isn't required."""
        return bool(self.azure_tenant_id and self.azure_api_client_id)

    def entra_group_to_role_map(self) -> dict[str, str]:
        """Build {entra_group_object_id: role_name} from the configured group ids.
        Empty entries are dropped — only mapped groups grant roles."""
        mapping = {
            self.entra_group_admin: "admin",
            self.entra_group_exec: "exec",
            self.entra_group_comp_viewer: "comp_viewer",
            self.entra_group_owner_ops: "owner_ops",
            self.entra_group_owner_finance: "owner_finance",
            self.entra_group_owner_clinical: "owner_clinical",
            self.entra_group_owner_hr: "owner_hr",
        }
        return {gid: role for gid, role in mapping.items() if gid}

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

    # ---------- Paycom workforce sync ----------
    # API enablement was requested with a 4–6 wk window. Until access is
    # granted, jobs/paycom_sync runs as a no-op stub when these are blank.
    # When the credential lands, drop them into Key Vault and let App Service
    # / the Container Apps Job env resolve them — same pattern as everything else.
    paycom_api_base_url: str = ""
    paycom_client_id: str = ""
    paycom_client_secret: str = ""

    @property
    def paycom_configured(self) -> bool:
        """True only when all three Paycom credentials are set. The cron job
        treats False as 'API access not yet granted' and exits 0 cleanly."""
        return bool(
            self.paycom_api_base_url
            and self.paycom_client_id
            and self.paycom_client_secret
        )


settings = Settings()

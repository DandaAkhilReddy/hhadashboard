from pydantic import BaseModel


class ClinicalSummary(BaseModel):
    hp_24h_pct: float
    hp_24h_target: int
    dc_48h_pct: float
    dc_48h_target: int
    los_fl_days: float
    los_tx_days: float
    los_woodmont_watch_days: float
    los_woodmont_trend_days: float
    credentials_expiring_30d: int
    credentials_expiring_60d: int
    credentials_expiring_90d: int


class CredentialExpiring(BaseModel):
    physician: str
    type: str
    expires_in_days: int
    expires_on: str
    tier: str  # "urgent" | "warning" | "info"

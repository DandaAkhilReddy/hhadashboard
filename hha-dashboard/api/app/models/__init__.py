"""SQLAlchemy models.

Every column MUST declare info={"data_class": "A"|"B"|"C"|"D"} per ADR-001.
tests/test_schema_classification.py enforces this at CI time.

Importing any model module registers it on Base.metadata. The test imports
every model module explicitly so the whole schema is visible to the check.
"""

from .alerts import AlertLog, AlertSubscription, CredentialAlertLog
from .audit import AuditLog
from .base import Base, DataClass, TimestampMixin
from .census_credentials import CensusCredential
from .entries import DailyEntry
from .entries_clinical import WeeklyClinical
from .entries_finance import MonthlyFinanceManual
from .entries_hr import WeeklyHrManual
from .uploads import UploadLog

__all__ = [
    "AlertLog",
    "AlertSubscription",
    "AuditLog",
    "Base",
    "CensusCredential",
    "CredentialAlertLog",
    "DailyEntry",
    "DataClass",
    "MonthlyFinanceManual",
    "TimestampMixin",
    "UploadLog",
    "WeeklyClinical",
    "WeeklyHrManual",
]

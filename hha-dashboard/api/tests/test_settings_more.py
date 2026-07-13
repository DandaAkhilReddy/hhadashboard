"""Extra tests for ``app.settings`` properties that the original
``test_settings.py`` did not cover:

- ``entra_configured`` — requires BOTH tenant + api-client id.
- ``telemetry_configured`` — just the App Insights connection string.
- ``entra_group_to_role_map()`` — drops empty group ids, preserves the
  rest as {group_id → role_name}.

The configured-booleans gate critical downstream behavior (lifespan
guard in app.main, OTel exporter wiring, role mapping). A regression
here is silent so worth pinning.
"""

from __future__ import annotations

import pytest

from app.settings import Settings

# ============================================================================
# entra_configured (lines 42-48)
# ============================================================================


class TestEntraConfigured:
    def test_false_when_both_unset(self) -> None:
        s = Settings(azure_tenant_id="", azure_api_client_id="")
        assert s.entra_configured is False

    def test_false_when_only_tenant_set(self) -> None:
        # Tenant alone is not enough — also need the API client id (audience).
        s = Settings(
            azure_tenant_id="00000000-0000-0000-0000-000000000001",
            azure_api_client_id="",
        )
        assert s.entra_configured is False

    def test_false_when_only_api_client_id_set(self) -> None:
        s = Settings(
            azure_tenant_id="",
            azure_api_client_id="api-app-id",
        )
        assert s.entra_configured is False

    def test_true_when_both_set(self) -> None:
        s = Settings(
            azure_tenant_id="00000000-0000-0000-0000-000000000001",
            azure_api_client_id="api-app-id",
        )
        assert s.entra_configured is True


# ============================================================================
# telemetry_configured (lines 148-153)
# ============================================================================


class TestTelemetryConfigured:
    def test_false_when_unset(self) -> None:
        s = Settings(applicationinsights_connection_string="")
        assert s.telemetry_configured is False

    def test_true_when_set(self) -> None:
        s = Settings(
            applicationinsights_connection_string=(
                "InstrumentationKey=00000000-0000-0000-0000-000000000001;"
                "IngestionEndpoint=https://eastus-1.in.applicationinsights.azure.com/"
            ),
        )
        assert s.telemetry_configured is True


# ============================================================================
# entra_group_to_role_map() (lines 50-62)
# ============================================================================


class TestEntraGroupToRoleMap:
    def test_empty_map_when_no_groups_configured(self) -> None:
        s = Settings(
            entra_group_admin="",
            entra_group_exec="",
            entra_group_comp_viewer="",
            entra_group_owner_ops="",
            entra_group_owner_finance="",
            entra_group_owner_clinical="",
            entra_group_owner_hr="",
        )
        assert s.entra_group_to_role_map() == {}

    def test_maps_every_configured_group_to_role(self) -> None:
        s = Settings(
            entra_group_admin="g-admin",
            entra_group_exec="g-exec",
            entra_group_comp_viewer="g-comp",
            entra_group_owner_ops="g-ops",
            entra_group_owner_finance="g-fin",
            entra_group_owner_clinical="g-clin",
            entra_group_owner_hr="g-hr",
        )
        assert s.entra_group_to_role_map() == {
            "g-admin": "admin",
            "g-exec": "exec",
            "g-comp": "comp_viewer",
            "g-ops": "owner_ops",
            "g-fin": "owner_finance",
            "g-clin": "owner_clinical",
            "g-hr": "owner_hr",
        }

    def test_drops_empty_group_ids(self) -> None:
        # Partial config: admin + owner_finance set, the rest empty.
        s = Settings(
            entra_group_admin="g-admin",
            entra_group_exec="",
            entra_group_comp_viewer="",
            entra_group_owner_ops="",
            entra_group_owner_finance="g-fin",
            entra_group_owner_clinical="",
            entra_group_owner_hr="",
        )
        out = s.entra_group_to_role_map()
        assert out == {"g-admin": "admin", "g-fin": "owner_finance"}
        # Empty string is NOT a key
        assert "" not in out

    @pytest.mark.parametrize(
        ("group_attr", "role_name"),
        [
            ("entra_group_admin", "admin"),
            ("entra_group_exec", "exec"),
            ("entra_group_comp_viewer", "comp_viewer"),
            ("entra_group_owner_ops", "owner_ops"),
            ("entra_group_owner_finance", "owner_finance"),
            ("entra_group_owner_clinical", "owner_clinical"),
            ("entra_group_owner_hr", "owner_hr"),
        ],
    )
    def test_each_role_maps_to_exactly_one_group(
        self, group_attr: str, role_name: str
    ) -> None:
        # Isolate one mapping per test so a typo in any single role is
        # caught explicitly. Locked names: admin/exec/comp_viewer/4 owner_*.
        kwargs = {group_attr: "g-single"}
        s = Settings(**kwargs)
        assert s.entra_group_to_role_map() == {"g-single": role_name}

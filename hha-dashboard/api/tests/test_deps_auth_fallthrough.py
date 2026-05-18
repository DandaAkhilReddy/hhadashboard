"""Auth fallthrough tests — ensure Path 3 in deps.get_current_user only
fires when both ENV=dev AND Entra is unconfigured.

Defense in depth around the lifespan startup assertion in app.main: even
if a deploy somehow lands with bad config, requests without auth must
401 in any non-dev environment.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.deps import get_current_user


@pytest.mark.asyncio
async def test_path3_fires_when_dev_and_entra_unconfigured() -> None:
    """The dev-default admin behavior — confirms existing tests keep working."""
    with patch("app.deps.settings") as s:
        s.env = "dev"
        s.entra_configured = False
        user = await get_current_user(authorization=None)
    assert user.upn == "dev-default@local"
    assert "admin" in user.roles


@pytest.mark.asyncio
async def test_path3_blocks_when_dev_but_entra_configured() -> None:
    """Even in dev, if Entra is configured we expect a real token. Path 3
    should NOT fire — request must 401."""
    with patch("app.deps.settings") as s:
        s.env = "dev"
        s.entra_configured = True
        with pytest.raises(HTTPException) as exc:
            await get_current_user(authorization=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_path3_blocks_in_prod_even_without_entra() -> None:
    """The fallthrough must NEVER admit users in non-dev environments —
    even if config is broken (entra_configured=False). The lifespan guard
    should prevent this state, but Path 3 is the second line of defense."""
    with patch("app.deps.settings") as s:
        s.env = "prod"
        s.entra_configured = False
        with pytest.raises(HTTPException) as exc:
            await get_current_user(authorization=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_path3_blocks_in_staging() -> None:
    """Any non-dev env name → 401 without credentials."""
    with patch("app.deps.settings") as s:
        s.env = "staging"
        s.entra_configured = True
        with pytest.raises(HTTPException) as exc:
            await get_current_user(authorization=None)
    assert exc.value.status_code == 401


# ----- Path 1: Real Entra JWT (Phase 3 gap-fill, lines 92-102) -----


@pytest.mark.asyncio
async def test_path1_verifies_bearer_token_when_entra_configured() -> None:
    """Bearer + entra_configured → calls verify_access_token, maps the
    extracted UPN + roles into CurrentUser. comp_viewer flag is set when
    'comp_viewer' is among the extracted roles."""
    from app.services.entra_jwt import VerifiedClaims

    fake_claims = VerifiedClaims.model_validate(
        {
            "preferred_username": "exec@hha.com",
            "aud": "x",
            "iss": "x",
        }
    )

    with (
        patch("app.deps.settings") as s,
        patch(
            "app.services.entra_jwt.verify_access_token",
            return_value=fake_claims,
        ) as mock_verify,
        patch(
            "app.services.entra_jwt.extract_upn",
            return_value="exec@hha.com",
        ),
        patch(
            "app.services.entra_jwt.extract_roles",
            return_value={"exec", "comp_viewer"},
        ),
    ):
        s.env = "prod"
        s.entra_configured = True
        user = await get_current_user(authorization="Bearer fake-jwt-token")

    mock_verify.assert_called_once()
    assert user.upn == "exec@hha.com"
    assert user.roles == {"exec", "comp_viewer"}
    assert user.comp_viewer is True


@pytest.mark.asyncio
async def test_path1_comp_viewer_false_when_role_absent() -> None:
    """A user with roles like {'exec'} but NOT 'comp_viewer' has
    comp_viewer=False — gates comp-sensitive endpoints."""
    from app.services.entra_jwt import VerifiedClaims

    fake_claims = VerifiedClaims.model_validate({"preferred_username": "ops@hha.com"})

    with (
        patch("app.deps.settings") as s,
        patch(
            "app.services.entra_jwt.verify_access_token",
            return_value=fake_claims,
        ),
        patch("app.services.entra_jwt.extract_upn", return_value="ops@hha.com"),
        patch("app.services.entra_jwt.extract_roles", return_value={"owner_ops"}),
    ):
        s.env = "prod"
        s.entra_configured = True
        user = await get_current_user(authorization="Bearer t")

    assert user.comp_viewer is False
    assert "owner_ops" in user.roles


# ----- Path 2: Invalid dev role (line 112) -----


@pytest.mark.asyncio
async def test_path2_rejects_invalid_dev_role_with_400() -> None:
    """Path 2 (Dev <role>) validates the role string against
    VALID_DEV_ROLES. A typo or made-up role → 400 with the valid set in
    the message — helps a dev debug without reading source."""
    with patch("app.deps.settings") as s:
        s.env = "dev"
        s.entra_configured = False
        with pytest.raises(HTTPException) as exc:
            await get_current_user(authorization="Dev not_a_real_role")

    assert exc.value.status_code == 400
    assert "Invalid dev role" in exc.value.detail
    assert "not_a_real_role" in exc.value.detail


@pytest.mark.asyncio
async def test_path2_accepts_every_documented_dev_role() -> None:
    """All six VALID_DEV_ROLES must work via Dev <role> header. If a future
    role rename breaks one, this catches it."""
    from app.deps import VALID_DEV_ROLES

    for role in VALID_DEV_ROLES:
        with patch("app.deps.settings") as s:
            s.env = "dev"
            s.entra_configured = False
            user = await get_current_user(authorization=f"Dev {role}")
        assert user.upn == f"dev-{role}@local"
        assert role in user.roles
        # comp_viewer only when role == admin per the dev-stub contract
        assert user.comp_viewer is (role == "admin")


# ----- require_comp_viewer guard (lines 158-163) -----


@pytest.mark.asyncio
async def test_require_comp_viewer_denies_when_flag_false() -> None:
    """Non-CEO/CFO user (comp_viewer=False) → 403 from the require_comp_viewer
    dependency. Protects /admin/comp-* and /scorecards comp columns."""
    from app.deps import CurrentUser, require_comp_viewer

    user = CurrentUser(upn="ops@hha.com", roles={"owner_ops"}, comp_viewer=False)

    with pytest.raises(HTTPException) as exc:
        await require_comp_viewer(user)

    assert exc.value.status_code == 403
    assert "comp_viewer" in exc.value.detail


@pytest.mark.asyncio
async def test_require_comp_viewer_allows_when_flag_true() -> None:
    """CEO/CFO (comp_viewer=True) → passes through, returns the user
    unchanged so the route handler can reuse it."""
    from app.deps import CurrentUser, require_comp_viewer

    user = CurrentUser(upn="ceo@hha.com", roles={"exec", "comp_viewer"}, comp_viewer=True)

    out = await require_comp_viewer(user)

    assert out is user
    assert out.upn == "ceo@hha.com"


# ----- require_role checker (already tested via 4xx integration tests, but
# pin the unit-level contract for clarity + speed) -----


@pytest.mark.asyncio
async def test_require_role_denies_when_user_has_no_matching_role() -> None:
    """owner_finance asking for owner_ops gate → 403 with the allowed
    roles in the message."""
    from app.deps import CurrentUser, require_role

    checker = require_role("admin", "owner_ops")
    user = CurrentUser(upn="finance@hha.com", roles={"owner_finance"}, comp_viewer=False)

    with pytest.raises(HTTPException) as exc:
        await checker(user)

    assert exc.value.status_code == 403
    assert "admin" in exc.value.detail
    assert "owner_ops" in exc.value.detail


@pytest.mark.asyncio
async def test_require_role_allows_when_user_has_any_matching_role() -> None:
    """Role check uses set-intersection, so a user with multiple roles
    passes if ANY of them is in the allowed set."""
    from app.deps import CurrentUser, require_role

    checker = require_role("admin", "owner_ops")
    user = CurrentUser(
        upn="multi@hha.com",
        roles={"owner_finance", "owner_ops"},
        comp_viewer=False,
    )

    out = await checker(user)
    assert out is user

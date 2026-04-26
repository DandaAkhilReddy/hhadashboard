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

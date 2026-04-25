"""Entra ID JWT verification.

Verifies access tokens issued by Microsoft Entra ID (formerly Azure AD)
against the tenant's published JWKS. On success, returns a `CurrentUser`
with UPN + roles derived from group membership claims.

Auth flow (frontend perspective):
  1. User signs in via MSAL.js → Entra issues an access token for our API
     scope (`api://<api-client-id>/access_as_user`).
  2. Frontend includes `Authorization: Bearer <jwt>` on every API call.
  3. This module validates the JWT and maps `groups` claim → role names.

Required claims we check:
  - `iss` (issuer) — must match `https://login.microsoftonline.com/<tenant>/v2.0`
  - `aud` (audience) — must match our API client_id
  - `exp` (expiry) — implicit, jose verifies
  - `nbf` (not-before) — implicit, jose verifies
  - signature — verified against the matching JWK by `kid`

Group → role mapping comes from settings.entra_group_to_role_map(). Only
explicitly configured group object_ids grant roles. A user with groups not
in the map gets an empty `roles` set (effectively read-nothing).

The `comp_viewer` role is additive: a user can be `exec` AND `comp_viewer`,
unlocking comp-sensitive endpoints.

JWKS keys are fetched once on first verification and cached in-process for
24 hours (Entra rotates keys infrequently and publishes overlapping keys
across rotations, so a stale cache is generally safe). On signature mismatch
we force a refresh in case of mid-flight rotation.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from fastapi import HTTPException, status
from jose import jwt
from jose.exceptions import (
    ExpiredSignatureError,
    JWTClaimsError,
    JWTError,
)

from ..settings import settings

log = logging.getLogger(__name__)

# JWKS cache: shared across requests, refreshed on miss / 24h expiry.
_JWKS_CACHE_TTL_SEC = 24 * 60 * 60
_jwks_cache: dict[str, Any] = {"keys": None, "fetched_at": 0.0}


def _jwks_url() -> str:
    return (
        f"https://login.microsoftonline.com/{settings.azure_tenant_id}"
        "/discovery/v2.0/keys"
    )


def _expected_issuer() -> str:
    return f"https://login.microsoftonline.com/{settings.azure_tenant_id}/v2.0"


async def _fetch_jwks(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    """Return the cached JWKS, fetching from Entra if expired or forced."""
    now = time.time()
    age = now - _jwks_cache["fetched_at"]
    if (
        not force_refresh
        and _jwks_cache["keys"] is not None
        and age < _JWKS_CACHE_TTL_SEC
    ):
        return _jwks_cache["keys"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_jwks_url())
        resp.raise_for_status()
        data = resp.json()

    _jwks_cache["keys"] = data["keys"]
    _jwks_cache["fetched_at"] = now
    log.info("entra.jwks.refreshed key_count=%d", len(data["keys"]))
    return data["keys"]


def _find_key(keys: list[dict[str, Any]], kid: str) -> dict[str, Any] | None:
    for k in keys:
        if k.get("kid") == kid:
            return k
    return None


async def verify_access_token(token: str) -> dict[str, Any]:
    """Verify the JWT and return the decoded claims.

    Raises HTTPException(401) on any validation failure. Never returns claims
    from an unverified token.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed token") from e

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing kid header")

    keys = await _fetch_jwks()
    key = _find_key(keys, kid)
    if key is None:
        # Possible mid-rotation — force refresh and retry once.
        keys = await _fetch_jwks(force_refresh=True)
        key = _find_key(keys, kid)
    if key is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "No matching signing key for token"
        )

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.azure_api_client_id,
            issuer=_expected_issuer(),
        )
    except ExpiredSignatureError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from e
    except JWTClaimsError as e:
        # Audience or issuer mismatch — be specific in the message for ops debugging
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"Invalid token claims: {e}"
        ) from e
    except JWTError as e:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"Token signature invalid: {e}"
        ) from e

    return claims


def extract_upn(claims: dict[str, Any]) -> str:
    """Pull the user's UPN from the token. Entra puts it in `preferred_username`
    for v2 tokens, or `upn` for v1. Fall back to `email`/`oid` for completeness.
    """
    for key in ("preferred_username", "upn", "email", "oid"):
        v = claims.get(key)
        if v:
            return str(v)
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Token missing UPN claim"
    )


def extract_roles(claims: dict[str, Any]) -> set[str]:
    """Map the token's `groups` claim (list of group object_ids) to role names
    via settings.entra_group_to_role_map()."""
    group_ids: list[str] = claims.get("groups") or []
    role_map = settings.entra_group_to_role_map()
    return {role_map[gid] for gid in group_ids if gid in role_map}

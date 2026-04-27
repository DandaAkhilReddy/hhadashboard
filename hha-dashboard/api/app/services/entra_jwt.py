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
from typing import Any, cast

import httpx
from fastapi import HTTPException, status
from jose import jwt
from jose.exceptions import (
    ExpiredSignatureError,
    JWTClaimsError,
    JWTError,
)
from pydantic import BaseModel, ConfigDict, ValidationError

from ..settings import settings

log = logging.getLogger(__name__)

# JWKS cache: shared across requests, refreshed on miss / 24h expiry.
_JWKS_CACHE_TTL_SEC = 24 * 60 * 60
_jwks_cache: dict[str, Any] = {"keys": None, "fetched_at": 0.0}


# ----- Verified-claims schema -----------------------------------------------
#
# The full Entra v2 token has 30+ claims; we only inspect a small subset to
# pull UPN + group memberships. Modelling those as a Pydantic schema (rather
# than a raw `dict[str, Any]`) gives us:
#   1. Type-shape validation. A malformed `groups` claim that arrives as a
#      single string instead of a list[str] would silently bypass role-map
#      lookup if we used `claims.get("groups") or []`. Pydantic raises here
#      so we 401 cleanly with a clear message.
#   2. mypy can prove `extract_upn` and `extract_roles` consume each field
#      with the right type. The audit's T7 finding ("Returning Any from
#      function declared to return Any") is gone.
#   3. `extra="allow"` keeps every other Entra claim (sub, tid, scp, idp,
#      ...) accessible via `model_extra` for future use without churning
#      the schema.
#
# Audit ticket T7.


class VerifiedClaims(BaseModel):
    """Typed view of a verified Entra JWT's claim set.

    All fields are `| None` because the standard claims set varies between
    v1 and v2 tokens, between user vs application tokens, and between
    tenants with different optional-claims configuration. `extract_upn`
    handles the precedence order; `extract_roles` handles missing-vs-empty.
    """

    model_config = ConfigDict(extra="allow")

    # Standard registered claims (RFC 7519)
    aud: str | None = None
    iss: str | None = None
    sub: str | None = None
    # Microsoft-specific identity claims
    preferred_username: str | None = None
    upn: str | None = None
    email: str | None = None
    oid: str | None = None
    name: str | None = None
    tid: str | None = None
    # Group membership — used by extract_roles to map to role names.
    # Strict-typed: a malformed scalar instead of a list raises ValidationError
    # at parse time, NOT a silent bypass at extract_roles time.
    groups: list[str] | None = None
    # Group-overage indirection (when user is in >150 groups). Not handled
    # operationally today — HHA's tenant has 7 groups — but we accept the
    # field so it doesn't go through `extra="allow"` and the audit log
    # records its presence if it ever appears in production.
    _claim_names: dict[str, str] | None = None


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
        return cast(list[dict[str, Any]], _jwks_cache["keys"])

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_jwks_url())
        resp.raise_for_status()
        data = resp.json()

    keys = cast(list[dict[str, Any]], data["keys"])
    _jwks_cache["keys"] = keys
    _jwks_cache["fetched_at"] = now
    log.info("entra.jwks.refreshed key_count=%d", len(keys))
    return keys


def _find_key(keys: list[dict[str, Any]], kid: str) -> dict[str, Any] | None:
    for k in keys:
        if k.get("kid") == kid:
            return k
    return None


async def verify_access_token(token: str) -> VerifiedClaims:
    """Verify the JWT and return the typed claims model.

    Raises HTTPException(401) on any validation failure (signature, expiry,
    audience, issuer, OR malformed claim shape — e.g. `groups` arriving as
    a string instead of list[str]). Never returns claims from an unverified
    token.
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
        raw_claims = jwt.decode(
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

    # Type-validate the claim shape. The signature is verified above; this
    # guards against a token whose payload is structurally weird (groups
    # claim as a string, etc.) — a silent role-bypass risk if we let it
    # flow through to extract_roles as `dict[str, Any]`.
    try:
        return VerifiedClaims.model_validate(raw_claims)
    except ValidationError as e:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"Token claim shape invalid: {e.errors(include_url=False)[:3]}",
        ) from e


def extract_upn(claims: VerifiedClaims) -> str:
    """Pull the user's UPN from the verified claims. Entra puts it in
    `preferred_username` for v2 tokens, or `upn` for v1. Fall back to
    `email`/`oid` for completeness.

    Raises HTTPException(401) when no identifier is present (a malformed
    token from Entra's perspective; should never happen in practice).
    """
    for value in (claims.preferred_username, claims.upn, claims.email, claims.oid):
        if value:
            return value
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Token missing UPN claim"
    )


def extract_roles(claims: VerifiedClaims) -> set[str]:
    """Map the token's `groups` claim (list of group object_ids) to role names
    via settings.entra_group_to_role_map().

    Returns an empty set if the user has no `groups` claim, no matching
    groups, or the claim is missing entirely. The Pydantic schema has
    already enforced that, if present, `groups` is a `list[str]`.

    Logs a single warning if `_claim_names` indirection is detected (user
    in >150 groups → Entra returns a callback URL instead of the list).
    HHA has 7 dashboard groups so this should never trigger; if it does,
    the user effectively has zero roles until we add Graph-API resolution.
    """
    if claims._claim_names and "groups" in claims._claim_names:
        log.warning(
            "entra.groups_overage_detected upn=%s — user in >150 groups; "
            "Graph-API resolution not implemented, returning empty role set",
            (claims.preferred_username or claims.upn or "<unknown>")[:64],
        )
        return set()

    group_ids = claims.groups or []
    role_map = settings.entra_group_to_role_map()
    return {role_map[gid] for gid in group_ids if gid in role_map}

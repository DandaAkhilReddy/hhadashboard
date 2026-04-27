"""Entra JWT verification tests.

Generates a fresh RSA keypair per test session, signs real JWTs against it,
serves the matching JWK via a monkeypatched `_fetch_jwks`. Tests:
  - happy path: valid token → claims returned, upn + roles extracted
  - expired token → 401
  - bad audience → 401
  - bad issuer → 401
  - missing kid → 401
  - missing key for kid → 401
  - groups → role mapping uses settings map
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jose import jwt
from jose.utils import base64url_encode

from app.services import entra_jwt as ej

TENANT_ID = "11111111-1111-1111-1111-111111111111"
API_CLIENT_ID = "22222222-2222-2222-2222-222222222222"
ISSUER = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"

GROUP_OPS = "33333333-3333-3333-3333-333333333333"
GROUP_FINANCE = "44444444-4444-4444-4444-444444444444"


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[rsa.RSAPrivateKey, dict[str, Any]]:
    """Generate one RSA keypair for the whole test module + return its JWK."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()

    def _b64uint(n: int) -> str:
        # Convert int → base64url-encoded big-endian bytes (no padding)
        byte_len = (n.bit_length() + 7) // 8
        return base64url_encode(n.to_bytes(byte_len, "big")).decode("ascii").rstrip("=")

    kid = "test-kid-" + uuid.uuid4().hex[:8]
    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64uint(public_numbers.n),
        "e": _b64uint(public_numbers.e),
    }
    return private_key, jwk


@pytest.fixture
def configured_entra(monkeypatch, rsa_keypair) -> Iterator[dict[str, Any]]:
    """Wire up settings + JWKS cache so the verifier sees a working tenant."""
    _, jwk = rsa_keypair
    monkeypatch.setattr(ej.settings, "azure_tenant_id", TENANT_ID, raising=False)
    monkeypatch.setattr(ej.settings, "azure_api_client_id", API_CLIENT_ID, raising=False)
    monkeypatch.setattr(ej.settings, "entra_group_owner_ops", GROUP_OPS, raising=False)
    monkeypatch.setattr(ej.settings, "entra_group_owner_finance", GROUP_FINANCE, raising=False)

    # Stub the JWKS fetch so the test never hits the network
    async def _fake_fetch(*, force_refresh: bool = False) -> list[dict[str, Any]]:
        _ = force_refresh
        return [jwk]

    monkeypatch.setattr(ej, "_fetch_jwks", _fake_fetch)
    return {"jwk": jwk}


def _sign(
    private_key: rsa.RSAPrivateKey,
    jwk: dict[str, Any],
    *,
    aud: str = API_CLIENT_ID,
    iss: str = ISSUER,
    upn: str = "alice@hha.com",
    groups: list[str] | None = None,
    extra_exp_offset: int = 3600,
) -> str:
    """Sign a JWT with the test private key."""
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    now = int(time.time())
    claims = {
        "aud": aud,
        "iss": iss,
        "iat": now,
        "nbf": now,
        "exp": now + extra_exp_offset,
        "preferred_username": upn,
    }
    if groups is not None:
        claims["groups"] = groups
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": jwk["kid"]})


# ---------- Happy path ----------


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured_entra")
async def test_verify_valid_token_returns_claims(rsa_keypair) -> None:
    private_key, jwk = rsa_keypair
    token = _sign(private_key, jwk, upn="alice@hha.com")

    claims = await ej.verify_access_token(token)

    assert isinstance(claims, ej.VerifiedClaims)
    assert claims.preferred_username == "alice@hha.com"
    assert claims.aud == API_CLIENT_ID
    assert claims.iss == ISSUER


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured_entra")
async def test_extract_upn_prefers_preferred_username(rsa_keypair) -> None:
    private_key, jwk = rsa_keypair
    token = _sign(private_key, jwk, upn="bob@hha.com")
    claims = await ej.verify_access_token(token)
    assert ej.extract_upn(claims) == "bob@hha.com"


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured_entra")
async def test_extract_roles_maps_groups_to_role_names(rsa_keypair) -> None:
    private_key, jwk = rsa_keypair
    token = _sign(private_key, jwk, groups=[GROUP_OPS, GROUP_FINANCE])

    claims = await ej.verify_access_token(token)
    roles = ej.extract_roles(claims)

    assert roles == {"owner_ops", "owner_finance"}


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured_entra")
async def test_extract_roles_drops_unknown_groups(rsa_keypair) -> None:
    private_key, jwk = rsa_keypair
    unknown_group = "99999999-9999-9999-9999-999999999999"
    token = _sign(private_key, jwk, groups=[GROUP_OPS, unknown_group])

    claims = await ej.verify_access_token(token)
    roles = ej.extract_roles(claims)

    assert roles == {"owner_ops"}  # unknown group silently dropped


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured_entra")
async def test_extract_roles_empty_when_no_groups_claim(rsa_keypair) -> None:
    private_key, jwk = rsa_keypair
    token = _sign(private_key, jwk, groups=None)

    claims = await ej.verify_access_token(token)
    roles = ej.extract_roles(claims)

    assert roles == set()


# ---------- Failure modes ----------


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured_entra")
async def test_expired_token_raises_401(rsa_keypair) -> None:
    private_key, jwk = rsa_keypair
    token = _sign(private_key, jwk, extra_exp_offset=-60)  # already expired

    with pytest.raises(HTTPException) as excinfo:
        await ej.verify_access_token(token)
    assert excinfo.value.status_code == 401
    assert "expired" in excinfo.value.detail.lower()


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured_entra")
async def test_bad_audience_raises_401(rsa_keypair) -> None:
    private_key, jwk = rsa_keypair
    token = _sign(private_key, jwk, aud="some-other-app")

    with pytest.raises(HTTPException) as excinfo:
        await ej.verify_access_token(token)
    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured_entra")
async def test_bad_issuer_raises_401(rsa_keypair) -> None:
    private_key, jwk = rsa_keypair
    token = _sign(private_key, jwk, iss="https://attacker.example.com/v2.0")

    with pytest.raises(HTTPException) as excinfo:
        await ej.verify_access_token(token)
    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured_entra")
async def test_malformed_token_raises_401() -> None:
    with pytest.raises(HTTPException) as excinfo:
        await ej.verify_access_token("not-even-a-jwt")
    assert excinfo.value.status_code == 401
    assert "malformed" in excinfo.value.detail.lower()


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured_entra")
async def test_token_with_unknown_kid_raises_401(rsa_keypair) -> None:
    """If the JWKS doesn't contain the kid (even after a force-refresh), 401."""
    private_key, _real_jwk = rsa_keypair
    bogus_jwk = {**_real_jwk, "kid": "kid-that-doesnt-exist"}
    token = _sign(private_key, bogus_jwk)

    with pytest.raises(HTTPException) as excinfo:
        await ej.verify_access_token(token)
    assert excinfo.value.status_code == 401


# ---------- UPN fallbacks ----------


def test_extract_upn_falls_through_to_email() -> None:
    claims = ej.VerifiedClaims(email="x@hha.com")
    assert ej.extract_upn(claims) == "x@hha.com"


def test_extract_upn_falls_through_to_oid() -> None:
    claims = ej.VerifiedClaims(oid="object-id-123")
    assert ej.extract_upn(claims) == "object-id-123"


def test_extract_upn_raises_when_no_id_claim() -> None:
    with pytest.raises(HTTPException) as excinfo:
        ej.extract_upn(ej.VerifiedClaims())
    assert excinfo.value.status_code == 401


# ---------- Type-shape validation (audit T7) ----------
#
# The audit's primary concern: a malformed `groups` claim (e.g. a single
# string instead of a list) used to silently bypass role-map lookup
# because `claims.get("groups") or []` accepts anything truthy. The new
# Pydantic schema validates the shape upfront and raises 401 if the
# token's payload is structurally weird.


def test_verified_claims_rejects_groups_as_scalar() -> None:
    """A 'groups' claim that's a single string instead of list[str] must
    fail Pydantic validation, not silently coerce."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ej.VerifiedClaims.model_validate(
            {"groups": "not-a-list-of-group-ids"}
        )


def test_verified_claims_rejects_groups_with_non_string_elements() -> None:
    """A 'groups' claim mixing types must fail validation."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ej.VerifiedClaims.model_validate(
            {"groups": [GROUP_OPS, 12345, None]}
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured_entra")
async def test_verify_rejects_malformed_groups_claim_with_401(rsa_keypair) -> None:
    """End-to-end: a JWT signed with an invalid 'groups' shape returns 401
    rather than letting the token pass with an empty role set (which would
    look identical to a legitimate user with no groups, masking the bug)."""
    private_key, jwk = rsa_keypair
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    now = int(time.time())
    bad_claims = {
        "aud": API_CLIENT_ID,
        "iss": ISSUER,
        "iat": now,
        "nbf": now,
        "exp": now + 3600,
        "preferred_username": "alice@hha.com",
        "groups": "not-a-list",  # malformed — a scalar where Pydantic expects list[str]
    }
    token = jwt.encode(bad_claims, pem, algorithm="RS256", headers={"kid": jwk["kid"]})

    with pytest.raises(HTTPException) as excinfo:
        await ej.verify_access_token(token)
    assert excinfo.value.status_code == 401
    assert "claim shape" in excinfo.value.detail.lower()


def test_extract_roles_is_empty_for_claim_names_overage() -> None:
    """If a user is in >150 groups, Entra returns `_claim_names` indirection
    instead of a populated `groups` claim. We don't (currently) resolve the
    Graph-API callback, so the user gets zero roles. Better than silently
    granting partial access from a stale `groups` field that may not be
    present."""
    claims = ej.VerifiedClaims.model_validate(
        {
            "preferred_username": "exec-with-many-groups@hha.com",
            "_claim_names": {"groups": "src1"},
        }
    )
    # Ensure the model actually captured the indirection (private attr access
    # via model_extra since Pydantic treats _-prefixed fields specially).
    # The point of this test is that extract_roles returns set() not crash.
    assert ej.extract_roles(claims) == set()

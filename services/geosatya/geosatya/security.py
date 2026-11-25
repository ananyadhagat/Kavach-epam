"""Passwords, access tokens (JWT) and access codes.

Only the Python standard library is used, so nothing new has to be installed:
- passwords: scrypt with a random salt per password (never stored in plain text);
- access tokens: JWT signed with HMAC-SHA256 (HS256 only; any other algorithm,
  including "none", is refused);
- access codes: compared in constant time against the value held by the server
  (environment variable), never sent to the browser.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time

SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_LEN = 2 ** 14, 8, 1, 32
PASSWORD_MIN, PASSWORD_MAX = 8, 128
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,120}\.[a-z]{2,24}$")
_PHONE = re.compile(r"^\+?[0-9]{10,15}$")


class TokenError(Exception):
    """The token is missing, malformed, forged or expired."""


# ----------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_LEN)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. With no stored hash a dummy hash is still computed,
    so the response time does not reveal whether an account exists."""
    if not stored:
        hashlib.scrypt(password.encode(), salt=b"0" * 16, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_LEN)
        return False
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(_unb64(digest)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, _unb64(digest))


def password_problem(password: str) -> str | None:
    if len(password) < PASSWORD_MIN:
        return f"Use at least {PASSWORD_MIN} characters for the password."
    if len(password) > PASSWORD_MAX:
        return f"Use at most {PASSWORD_MAX} characters for the password."
    if password.isdigit() or password.isalpha():
        return "Use letters and numbers in the password."
    return None


def normalise_login(raw: str) -> str | None:
    """An email address (lower case) or a phone number (digits, optional +).
    Returns None when it is neither."""
    value = (raw or "").strip().lower()
    phone = re.sub(r"[\s\-()]", "", value)
    if _PHONE.match(phone):
        return phone
    if _EMAIL.match(value):
        return value
    return None


# --------------------------------------------------------- access codes
def code_matches(given: str | None, expected: str) -> bool:
    """False when no code is configured: a missing code never opens a door."""
    if not expected or not given:
        return False
    return hmac.compare_digest(given.strip().encode(), expected.strip().encode())


# --------------------------------------------------------------- tokens
def make_token(secret: str, *, user_id: str, role: str, platform_role: str | None, epoch: int, ttl_s: int) -> str:
    now = int(time.time())
    claims = {"iss": "kavach", "sub": user_id, "role": role, "prole": platform_role, "ep": epoch,
              "iat": now, "exp": now + ttl_s, "jti": secrets.token_hex(8)}
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def read_token(secret: str, token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenError("malformed")
    header_b, body_b, sig_b = parts
    try:
        header = json.loads(_unb64(header_b))
        claims = json.loads(_unb64(body_b))
        sig = _unb64(sig_b)
    except (ValueError, TypeError) as exc:
        raise TokenError("malformed") from exc
    if not isinstance(header, dict) or header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise TokenError("algorithm not allowed")
    expected = hmac.new(secret.encode(), f"{header_b}.{body_b}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise TokenError("bad signature")
    if not isinstance(claims, dict) or claims.get("iss") != "kavach" or not isinstance(claims.get("sub"), str):
        raise TokenError("bad claims")
    now = int(time.time())
    if not isinstance(claims.get("exp"), int) or claims["exp"] <= now:
        raise TokenError("expired")
    if not isinstance(claims.get("iat"), int) or claims["iat"] > now + 60:
        raise TokenError("issued in the future")
    return claims


def looks_like_jwt(token: str) -> bool:
    return token.count(".") == 2


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

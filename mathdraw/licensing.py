"""Offline licence keys (Ed25519 signatures) + free trial.

How it works
------------
* You (the seller) generate a key pair once with tools/make_signing_keys.py.
  The PRIVATE key stays with you; the public key is written to
  mathdraw/license_pubkey.txt and ships inside the app.
* For each sale, tools/issue_license.py "Buyer Name" buyer@email signs a small
  JSON payload.  The buyer pastes the resulting key into Help → Enter licence key.
* The app verifies the signature with the public key — no server, no internet.
  Keys cannot be forged without your private key.  (Like every offline scheme,
  a determined cracker can patch the program itself; this keeps honest people
  honest, which is the realistic goal.)
* If license_pubkey.txt is missing/empty, licensing is disabled (developer build).
"""
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass

from .branding import PRODUCT_CODE, TRIAL_DAYS

PUBKEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "license_pubkey.txt")
KEY_PREFIX = "MD1-"


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def load_public_key(path: str = PUBKEY_FILE):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            txt = "".join(l.strip() for l in fh if l.strip() and not l.startswith("#"))
    except FileNotFoundError:
        return None
    if not txt:
        return None
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    return Ed25519PublicKey.from_public_bytes(base64.b64decode(txt))


def sign_license(private_key, name: str, email: str, extra: dict | None = None) -> str:
    payload = {"p": PRODUCT_CODE, "n": name, "e": email, "t": int(time.time()), "id": _b64e(os.urandom(6))}
    if extra:
        payload.update(extra)
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    sig = private_key.sign(raw)
    return KEY_PREFIX + _b64e(raw) + "." + _b64e(sig)


def verify_license(key: str, public_key) -> dict | None:
    """Payload dict if the key is genuine for this product, else None."""
    if not key or public_key is None:
        return None
    k = "".join(key.split())  # tolerate line breaks/spaces from e-mail clients
    if k.startswith(KEY_PREFIX):
        k = k[len(KEY_PREFIX):]
    try:
        body, sig = k.split(".", 1)
        raw = _b64d(body)
        public_key.verify(_b64d(sig), raw)
        payload = json.loads(raw.decode())
    except Exception:
        return None
    if payload.get("p") != PRODUCT_CODE:
        return None
    return payload


@dataclass
class LicenseStatus:
    state: str  # "disabled" | "licensed" | "trial" | "expired"
    days_left: int = 0
    licensee: str = ""

    @property
    def allowed(self) -> bool:
        return self.state in ("disabled", "licensed", "trial")

    def title_suffix(self) -> str:
        if self.state == "trial":
            return f" — Trial: {self.days_left} day{'s' if self.days_left != 1 else ''} left"
        if self.state == "expired":
            return " — Trial expired"
        return ""


def evaluate(key: str, first_run_ts: float, now: float | None = None, public_key="load") -> LicenseStatus:
    pk = load_public_key() if public_key == "load" else public_key
    if pk is None:
        return LicenseStatus("disabled")
    payload = verify_license(key, pk)
    if payload:
        return LicenseStatus("licensed", licensee=payload.get("n", ""))
    now = time.time() if now is None else now
    start = first_run_ts or now
    left = TRIAL_DAYS - int((now - start) // 86400)
    if left > 0:
        return LicenseStatus("trial", days_left=left)
    return LicenseStatus("expired")

"""Create the licence-signing key pair (run ONCE, before your first sale).

    python tools/make_signing_keys.py

Writes:
  tools/PRIVATE_signing_key.pem   — SECRET.  Back it up somewhere safe (password
                                     manager / encrypted drive).  Never ship it,
                                     never commit it.  Lose it and you can't issue
                                     keys that existing builds accept.
  mathdraw/license_pubkey.txt      — public key, bundled into the app.  From now on
                                     builds require a licence (after the trial).
"""
import base64
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIV = os.path.join(ROOT, "tools", "PRIVATE_signing_key.pem")
PUB = os.path.join(ROOT, "mathdraw", "license_pubkey.txt")

if os.path.exists(PRIV):
    sys.exit(f"Refusing to overwrite {PRIV}: replacing it would invalidate every key you have issued.")
key = Ed25519PrivateKey.generate()
with open(PRIV, "wb") as fh:
    fh.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
with open(PUB, "w", encoding="utf-8") as fh:
    fh.write("# Licence-verification public key (safe to ship)\n" + base64.b64encode(pub).decode() + "\n")
print("Private key :", PRIV, " <-- BACK THIS UP, KEEP IT SECRET")
print("Public key  :", PUB)

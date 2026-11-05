"""Issue a licence key for a buyer.

    python tools/issue_license.py "Ada Lovelace" ada@example.com

Prints the key to e-mail to the buyer (also appends it to tools/issued_licenses.csv
so you have a record for support/refunds).
"""
import csv
import datetime
import os
import sys

from cryptography.hazmat.primitives import serialization

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from mathdraw.licensing import load_public_key, sign_license, verify_license  # noqa: E402

USAGE = ('usage:\n  python tools/issue_license.py "Buyer Name" buyer@email\n'
         '  python tools/issue_license.py --batch 100      (generic keys, e.g. to upload to a storefront key list)')
if len(sys.argv) < 3:
    sys.exit(USAGE)
with open(os.path.join(ROOT, "tools", "PRIVATE_signing_key.pem"), "rb") as fh:
    priv = serialization.load_pem_private_key(fh.read(), password=None)
pub = load_public_key()
if sys.argv[1] == "--batch":
    people = [("Licensed user", "") for _ in range(int(sys.argv[2]))]
else:
    people = [(sys.argv[1], sys.argv[2])]
log = os.path.join(ROOT, "tools", "issued_licenses.csv")
with open(log, "a", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    for name, email in people:
        key = sign_license(priv, name, email)
        assert verify_license(key, pub), "key does not match mathdraw/license_pubkey.txt"
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), name, email, key])
        print(key)

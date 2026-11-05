"""Product identity — EDIT THIS FILE before you publish.

Everything user-visible about the product's name, company and links comes
from here (window titles, About box, activation dialog, installer metadata
via packaging/mathdraw.spec and packaging/installer.iss).

NOTE: "MathDraw" is a working title only.  Texas Instruments already uses
"MathDraw" for a gesture-drawing feature in TI-Nspire, so choose your own
name and check trademarks before selling.
"""

APP_NAME = "MathDraw"  # <- your product name
APP_ID = "MathDraw"  # folder name for settings/logs (%LOCALAPPDATA%\<APP_ID>); keep stable after release
VERSION = "1.0.0"
PUBLISHER = "Your Company Name"  # <- legal name of the seller
WEBSITE = "https://example.com"  # <- product website
BUY_URL = "https://example.com/buy"  # <- checkout page (Lemon Squeezy / Gumroad / Paddle …)
SUPPORT_EMAIL = "support@example.com"  # <- support address
COPYRIGHT_YEAR = "2026"

# Licensing.  Licence checks only switch on once a public key exists
# (run tools/make_signing_keys.py).  Until then the app runs unrestricted
# ("developer build").
TRIAL_DAYS = 14
PRODUCT_CODE = "mathdraw"  # embedded in licence keys; change if you rename, before issuing any keys

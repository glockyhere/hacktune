"""
==============================================================================
  THE ONLY FILE YOU NORMALLY EDIT.
  Put your real payment card, contacts, price and license public key here.
==============================================================================

Nothing secret lives in this file. It ships inside the .exe, so a buyer can
read it. That is fine: the card/contacts are *meant* to be shown, and the
LICENSE_PUBLIC_KEY can only VERIFY licenses, never create them. The matching
private key (that mints keys) stays on your machine in keygen/ and is NEVER
distributed.
"""

# ---- Product ----------------------------------------------------------------
PRODUCT_NAME = "Car APK Installer"
PRODUCT_VERSION = "1.0.0"
PRICE_TEXT = "200 000 so'm"        # shown on the paywall, free text

# ---- How the buyer pays YOU (shown on the paywall screen) -------------------
# These are displayed as text for a manual card-to-card transfer. This is your
# own info for RECEIVING money — the app never asks the buyer for THEIR card.
PAYMENT = {
    "card_number": "0000 0000 0000 0000",   # <-- your Uzcard/Humo/etc. number
    "card_holder": "YOUR NAME",              # <-- name on the card
    "bank_hint":   "Uzcard / Humo",          # optional free text
}
CONTACTS = {
    "telegram": "@your_telegram",            # <-- how buyers reach you for the key
    "phone":    "+998 00 000 00 00",
    "email":    "you@example.com",
}

# Instructions shown under the payment box (free text, multi-line ok).
PAYMENT_INSTRUCTIONS = (
    "1. Transfer the price to the card above.\n"
    "2. Send your Machine ID (shown below) + payment screenshot to the contact.\n"
    "3. You will receive a license key. Paste it and press Activate."
)

# ---- Licensing --------------------------------------------------------------
# Paste the PUBLIC key printed by  keygen/generate_keys.py  here (one line,
# base64). Leave as the placeholder only while testing — activation will refuse
# every key until a real public key is set.
LICENSE_PUBLIC_KEY = "PASTE_PUBLIC_KEY_FROM_generate_keys.py_HERE"

# Product tag embedded in every license. Keeps keys for THIS product from
# unlocking a different product you might sell later. Change per product.
LICENSE_PRODUCT_TAG = "carapk-v1"

# ---- Activation backend (per-install approval) ------------------------------
# Your Cloudflare Worker base URL (from `wrangler deploy`), e.g.
#   https://carapk-activation.<your-subdomain>.workers.dev
ACTIVATION_API_URL = "https://carapk-activation.example.workers.dev"
# The ACTIVATION_PUBLIC_KEY printed by keygen/generate_activation_keys.py.
# The program verifies activation tokens with this; it can never mint them.
ACTIVATION_PUBLIC_KEY = "PASTE_ACTIVATION_PUBLIC_KEY_HERE"

# ---- Cloud payload ----------------------------------------------------------
# The APKs are NOT bundled — the program downloads them from here every run.
# Upload the five files from payload/ to any static host (your own storage,
# object storage, a release bucket, etc.) and put that folder URL here, WITH the
# trailing slash. The program requests APK_BASE_URL + <filename>.
# Each file's SHA-256 is pinned in the app (app/provision.py), so a wrong or
# tampered download is rejected before anything is installed.
APK_BASE_URL = "https://pub-ded3ae84f48f43ac986e4968911418c4.r2.dev/"

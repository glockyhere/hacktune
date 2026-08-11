"""
SELLER TOOL — mint one license key for a paying customer.

    python issue_license.py <MACHINE_ID> [--days N] [--ref "buyer note"]

  <MACHINE_ID>  the id the buyer reads off the paywall screen (ABCD-EF12-...)
  --days N      optional expiry in N days (omit = perpetual)
  --ref "..."   optional note stored in the key (e.g. buyer name / order id)

Prints the license key. Send it to the buyer; they paste + Activate.

The product tag must match app/config.py LICENSE_PRODUCT_TAG.
"""
import argparse
import base64
import json
import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PRODUCT_TAG = "carapk-v1"   # keep in sync with app/config.py LICENSE_PRODUCT_TAG


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def load_private() -> Ed25519PrivateKey:
    p = Path(__file__).resolve().parent / "license_private.key"
    if not p.exists():
        raise SystemExit("license_private.key not found. Run generate_keys.py first.")
    raw = base64.urlsafe_b64decode(p.read_text().strip() + "==")
    return Ed25519PrivateKey.from_private_bytes(raw)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("machine_id")
    ap.add_argument("--days", type=int, default=0, help="expiry in days (0 = never)")
    ap.add_argument("--ref", default="", help="buyer reference note")
    args = ap.parse_args()

    mid = args.machine_id.strip().upper()
    now = int(time.time())
    exp = now + args.days * 86400 if args.days > 0 else 0

    payload = {"mid": mid, "tag": PRODUCT_TAG, "iss": now, "exp": exp, "ref": args.ref}
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()

    priv = load_private()
    sig = priv.sign(payload_bytes)
    license_str = b64url(payload_bytes) + "." + b64url(sig)

    print("=" * 70)
    print(f"Machine ID : {mid}")
    print(f"Expiry     : {'never' if not exp else time.strftime('%Y-%m-%d', time.localtime(exp))}")
    if args.ref:
        print(f"Reference  : {args.ref}")
    print("\nLICENSE KEY (send to buyer):\n")
    print(license_str)
    print("=" * 70)


if __name__ == "__main__":
    main()

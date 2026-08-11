"""
SELLER TOOL — run this ONCE. Creates your license signing keypair.

    python generate_keys.py

Outputs:
  * keygen/license_private.key   <-- KEEP SECRET. Never ship. Back it up.
  * prints the PUBLIC key        <-- paste into app/config.py LICENSE_PUBLIC_KEY

If the private key leaks, anyone can mint keys and your paywall is void.
If you lose it, you can no longer issue keys for the public key already shipped.
"""
import base64
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def main() -> None:
    here = Path(__file__).resolve().parent
    priv_path = here / "license_private.key"
    if priv_path.exists():
        print(f"Refusing to overwrite existing {priv_path.name}. "
              f"Delete it first if you really want a new keypair.")
        return

    priv = Ed25519PrivateKey.generate()
    raw_priv = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    priv_path.write_text(b64url(raw_priv), encoding="utf-8")
    try:
        import os
        os.chmod(priv_path, 0o600)
    except Exception:
        pass

    print("=" * 70)
    print("Keypair created.")
    print(f"  PRIVATE key saved to: {priv_path}   (keep secret, back it up)")
    print()
    print("  PUBLIC key — paste this into app/config.py LICENSE_PUBLIC_KEY:")
    print()
    print("    " + b64url(raw_pub))
    print("=" * 70)


if __name__ == "__main__":
    main()

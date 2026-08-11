"""
SELLER TOOL — run once. Creates the activation-server signing keypair.

    python generate_activation_keys.py

Prints:
  * ACTIVATION_PUBLIC_KEY  -> paste into app/config.py (the program verifies with it)
  * ACTIVATION_PRIVATE_PKCS8 -> set as a Cloudflare Worker SECRET (the server signs
                                with it). NEVER commit or ship this.

The private key only ever lives in your Worker. The app ships only the public key,
so no buyer can mint or approve their own activation.
"""
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def main() -> None:
    priv = Ed25519PrivateKey.generate()
    pkcs8 = priv.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    print("=" * 70)
    print("ACTIVATION_PUBLIC_KEY  (paste into app/config.py):\n")
    print("   " + b64url(pub_raw))
    print("\nACTIVATION_PRIVATE_PKCS8  (Cloudflare Worker secret — keep secret):\n")
    print("   " + b64(pkcs8))
    print("=" * 70)
    print("Set the secret with:\n")
    print("   cd server && npx wrangler secret put SIGNING_KEY_PKCS8")
    print("   (paste the ACTIVATION_PRIVATE_PKCS8 value when prompted)")
    print("=" * 70)


if __name__ == "__main__":
    main()

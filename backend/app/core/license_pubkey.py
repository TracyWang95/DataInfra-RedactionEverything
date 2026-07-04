"""Vendor Ed25519 public key for offline license verification.

Baked into the build on purpose and NOT env-overridable: the verifier must
never be redirectable to a different key at runtime. Each customer build gets
its own keypair — regenerate with tools/license_gen (``keygen``) and replace
the hex below before producing a customer bundle. The matching private key
stays with the vendor and is never shipped.
"""

PUBLIC_KEY_HEX = "291c9c80654fd61d2389102ceec58486beb4a5bc0c86ba0ca2f177905083883b"

# License Generator (vendor side)

- `python generate_license.py keygen --out priv.pem` — new Ed25519 keypair; bake the printed pubkey hex into `backend/app/core/license_pubkey.py`.
- `python generate_license.py issue --customer "客户名" --expires 2027-06-30 --max-users 50 --edition enterprise --industries legal,medical --key priv.pem --out license.json` — sign + self-verify; ship `license.json` to the customer (`DATA_DIR/license.json` or upload via `POST /api/v1/license/upload`).
- Run inside the backend virtualenv (needs `cryptography` + backend importable).
- This directory MUST be excluded from customer bundles; private keys never leave the vendor.

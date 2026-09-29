"""Create local credentials without overwriting an existing configuration."""

import os
from pathlib import Path
import secrets


target = Path(__file__).resolve().parents[1] / ".env"
names = (
    "POSTGRES_PASSWORD",
    "IRIS_NRW_PASSWORD",
    "IRIS_PEAT_PASSWORD",
    "IRIS_PROMOTER_PASSWORD",
    "IRIS_APP_PASSWORD",
)
try:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(".env already exists; kept existing credentials unchanged.")
with os.fdopen(fd, "w") as stream:
    stream.write("# Generated local-only credentials; do not commit.\n")
    for name in names:
        stream.write(f"{name}={secrets.token_hex(24)}\n")
print("Created .env with independent local passwords.")

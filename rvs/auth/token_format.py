"""Public credential encoding checks; only the server decides authority."""

import base64
import re


def validate_public_token(value: str, *, native: bool = False) -> str:
    markers = "rvs_slt" if native else "rvs_ust|rvs_uot|rvs_oat"
    match = re.fullmatch(rf"({markers})([A-Za-z0-9_-]{{43}})", value)
    if match is None:
        raise ValueError("Invalid public credential format")
    suffix = match[2]
    decoded = base64.b64decode(suffix + "=", altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(decoded).decode().rstrip("=") != suffix:
        raise ValueError("Invalid public credential encoding")
    return value

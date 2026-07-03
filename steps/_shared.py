from __future__ import annotations

import os

from pydantic import SecretStr


def require_api_key() -> SecretStr:
    value = os.getenv("OPENAI_API_KEY")
    if not value:
        raise RuntimeError("Configura OPENAI_API_KEY prima di eseguire questo step.")
    return SecretStr(value)


from src.models.auth_identity import AuthIdentity
from src.repositories.auth_identity_repo import (
    PROVIDER_EMAIL,
    PROVIDER_PHONE,
    PROVIDER_TELEGRAM,
)


# Человекочитаемое значение auth_identity для админки и API.
def auth_identity_display_value(identity: AuthIdentity) -> str:
    if identity.provider == PROVIDER_EMAIL:
        email = (identity.email or "").strip()
        return email or identity.provider_user_id
    if identity.provider == PROVIDER_PHONE:
        return identity.provider_user_id.strip()
    if identity.provider == PROVIDER_TELEGRAM:
        meta = identity.meta_json if isinstance(identity.meta_json, dict) else {}
        username = meta.get("username")
        if username:
            normalized = str(username).strip().lstrip("@")
            if normalized:
                return f"@{normalized}"
        return identity.provider_user_id
    return identity.provider_user_id or identity.provider

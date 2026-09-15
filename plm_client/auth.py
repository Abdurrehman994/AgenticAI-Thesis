"""3DPassport (CAS) login and the 3DSpace CSRF token.

Flow: fetch a login ticket (lt) from 3DPassport, post credentials with 3DSpace as
the CAS service so the redirect sets the 3DSpace session cookies in the jar, then
read ENO_CSRF_TOKEN from 3DSpace. Write calls need that token; reads do not.
"""
import requests

from .config import Settings


class AuthError(RuntimeError):
    pass


def login(http: requests.Session, cfg: Settings) -> None:
    resp = http.get(
        f"{cfg.passport_url}/login",
        params={"action": "get_auth_params"},
        timeout=cfg.timeout,
    )
    resp.raise_for_status()
    lt = resp.json().get("lt")
    if not lt:
        raise AuthError("3DPassport did not return a login ticket (lt)")

    # Not status-checked: the 3DSpace landing page answers 403 even after a successful
    # login (the session cookies are already set). fetch_csrf is the real success check.
    http.post(
        f"{cfg.passport_url}/login",
        params={"service": cfg.space_url},
        data={"lt": lt, "username": cfg.username, "password": cfg.password},
        timeout=cfg.timeout,
    )


def fetch_csrf(http: requests.Session, cfg: Settings) -> str:
    resp = http.get(
        f"{cfg.space_url}/resources/v1/application/CSRF",
        params={"tenant": cfg.tenant} if cfg.tenant else None,
        timeout=cfg.timeout,
    )
    try:
        token = resp.json()["csrf"]["value"]
    except (ValueError, KeyError, TypeError):
        # A failed CAS login leaves no 3DSpace session, so this call gets a login page or 401
        raise AuthError(
            f"No CSRF token from 3DSpace (HTTP {resp.status_code}). Login probably failed: "
            "check PLM_USERNAME/PLM_PASSWORD, PLM_SPACE_URL, and whether the account needs MFA."
        ) from None
    return token

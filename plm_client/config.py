"""Tenant settings, read from environment variables (or a local .env file)."""
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

from dotenv import load_dotenv

REQUIRED = (
    "PLM_SPACE_URL",
    "PLM_PASSPORT_URL",
    "PLM_USERNAME",
    "PLM_PASSWORD",
    "PLM_SECURITY_CONTEXT",
)


def tenant_from_url(space_url: str) -> str:
    """https://r1132101930766-eu1-academia-space.3dexperience.3ds.com -> R1132101930766"""
    return (urlparse(space_url).hostname or "").split("-")[0].upper()


@dataclass(frozen=True)
class Settings:
    space_url: str  # 3DSpace root, e.g. https://r1234-eu1-space.3dexperience.3ds.com/enovia
    passport_url: str  # 3DPassport root, e.g. https://eu1-ds-iam.3dexperience.3ds.com
    username: str
    password: str = field(repr=False)
    security_context: str  # Role.Organization.CollabSpace, sent as the SecurityContext header
    tenant: str = ""  # cloud 3DSpace answers "tenant does not exist" unless ?tenant= is sent
    timeout: float = 30.0

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        missing = [name for name in REQUIRED if not os.getenv(name)]
        if missing:
            raise RuntimeError(
                f"Missing environment variables: {', '.join(missing)} (copy .env.example to .env)"
            )
        space_url = os.environ["PLM_SPACE_URL"].rstrip("/")
        return cls(
            space_url=space_url,
            passport_url=os.environ["PLM_PASSPORT_URL"].rstrip("/"),
            username=os.environ["PLM_USERNAME"],
            password=os.environ["PLM_PASSWORD"],
            security_context=os.environ["PLM_SECURITY_CONTEXT"],
            tenant=os.getenv("PLM_TENANT") or tenant_from_url(space_url),
            timeout=float(os.getenv("PLM_TIMEOUT", "30")),
        )

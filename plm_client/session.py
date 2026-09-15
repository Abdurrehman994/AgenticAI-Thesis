"""requests.Session wrapper that adds SecurityContext / ENO_CSRF_TOKEN and re-logs in on 401."""
import requests

from . import auth
from .config import Settings

MODELER_PATH = "/resources/v1/modeler"


class PLMError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message

    @classmethod
    def from_response(cls, resp: requests.Response) -> "PLMError":
        # dseng error bodies are {"status": int, "message": str}
        try:
            message = resp.json().get("message") or resp.text
        except ValueError:
            message = resp.text
        return cls(resp.status_code, message[:500])


class PLMSession:
    def __init__(self, cfg: Settings, http: requests.Session | None = None):
        self.cfg = cfg
        self.http = http or requests.Session()
        self.http.headers["Accept"] = "application/json"
        self._csrf: str | None = None

    def login(self) -> None:
        auth.login(self.http, self.cfg)
        self._csrf = auth.fetch_csrf(self.http, self.cfg)

    def request(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> dict:
        """Call {space}/resources/v1/modeler{path} and return the decoded JSON body."""
        if self._csrf is None:
            self.login()
        resp = self._send(method, path, params, json)
        if resp.status_code == 401:
            self.login()
            resp = self._send(method, path, params, json)
        if not resp.ok:
            raise PLMError.from_response(resp)
        return resp.json() if resp.content else {}

    def _send(self, method: str, path: str, params: dict | None, json: dict | None) -> requests.Response:
        headers = {"SecurityContext": self.cfg.security_context}
        if method.upper() != "GET":
            headers["ENO_CSRF_TOKEN"] = self._csrf
        if self.cfg.tenant:
            params = {"tenant": self.cfg.tenant, **(params or {})}
        return self.http.request(
            method,
            f"{self.cfg.space_url}{MODELER_PATH}{path}",
            headers=headers,
            params=params,
            json=json,
            timeout=self.cfg.timeout,
        )

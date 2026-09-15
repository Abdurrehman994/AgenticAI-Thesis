import pytest

from plm_client import Engineering, PLMError, PLMSession, Settings

CFG = Settings(
    space_url="https://space.test/enovia",
    passport_url="https://passport.test",
    username="u",
    password="p",
    security_context="VPLMProjectLeader.Company.API_development",
    tenant="R0000000000001",
)


class FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self.ok = status_code < 400
        self._body = body or {}
        self.content = b"x"
        self.text = str(self._body)

    def json(self) -> dict:
        return self._body


class FakeHttp:
    def __init__(self, *responses: FakeResponse):
        self.headers = {}
        self.calls = []
        self._responses = list(responses)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self._responses.pop(0)


@pytest.fixture
def logins(monkeypatch):
    count = []
    monkeypatch.setattr("plm_client.auth.login", lambda http, cfg: count.append(1))
    monkeypatch.setattr("plm_client.auth.fetch_csrf", lambda http, cfg: f"token{len(count)}")
    return count


def test_csrf_only_on_writes(logins):
    http = FakeHttp(FakeResponse(200, {"member": []}), FakeResponse(200, {"member": [{}]}))
    session = PLMSession(CFG, http)
    session.request("GET", "/dseng/dseng:EngItem/search")
    session.request("PATCH", "/dseng/dseng:EngItem/X", json={"cestamp": "c"})

    get_headers, patch_headers = http.calls[0][2]["headers"], http.calls[1][2]["headers"]
    assert get_headers == {"SecurityContext": CFG.security_context}
    assert patch_headers["ENO_CSRF_TOKEN"] == "token1"
    assert http.calls[0][1] == "https://space.test/enovia/resources/v1/modeler/dseng/dseng:EngItem/search"


def test_tenant_sent_with_every_call(logins):
    http = FakeHttp(FakeResponse(200, {"member": []}))
    Engineering(PLMSession(CFG, http)).search_items("API", top=5)
    assert http.calls[0][2]["params"]["tenant"] == "R0000000000001"
    assert http.calls[0][2]["params"]["$top"] == 5


def test_tenant_derived_from_space_url():
    from plm_client.config import tenant_from_url

    assert tenant_from_url("https://r1132101930766-eu1-academia-space.3dexperience.3ds.com/enovia") == "R1132101930766"


def test_relogin_once_on_401(logins):
    http = FakeHttp(FakeResponse(401), FakeResponse(200, {"member": []}))
    PLMSession(CFG, http).request("PATCH", "/x", json={})
    assert len(logins) == 2
    assert http.calls[1][2]["headers"]["ENO_CSRF_TOKEN"] == "token2"


def test_error_message_from_body(logins):
    http = FakeHttp(FakeResponse(400, {"status": 400, "message": "cestamp is outdated"}))
    with pytest.raises(PLMError, match="cestamp is outdated"):
        PLMSession(CFG, http).request("PATCH", "/x", json={})


def test_patch_fetches_cestamp_when_missing(logins):
    http = FakeHttp(
        FakeResponse(200, {"member": [{"id": "X", "cestamp": "abc"}]}),
        FakeResponse(200, {"member": [{"id": "X", "description": "new"}]}),
    )
    updated = Engineering(PLMSession(CFG, http)).patch_item("X", {"description": "new"})
    assert http.calls[1][2]["json"] == {"description": "new", "cestamp": "abc"}
    assert updated["description"] == "new"


def test_add_instance_references_child_by_space_url(logins):
    http = FakeHttp(FakeResponse(200, {"member": [{"id": "I"}]}))
    Engineering(PLMSession(CFG, http)).add_instance("P", "C", name="C.1")
    _, url, kwargs = http.calls[0]
    assert url.endswith("/dseng/dseng:EngItem/P/dseng:EngInstance")
    assert kwargs["json"]["instances"][0]["referencedObject"] == {
        "source": "https://space.test/enovia",
        "type": "dseng:EngItem",
        "identifier": "C",
        "relativePath": "/resources/v1/modeler/dseng/dseng:EngItem/C",
    }

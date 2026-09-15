from vcr.request import Request

from plm_client.recording import _scrub_request, _scrub_response


def test_cas_ticket_removed_from_request_uri():
    request = _scrub_request(Request("GET", "https://space.test/enovia/?ticket=ST-1-abc&tenant=R1", "", {}))
    assert "ST-1" not in request.uri
    assert "tenant=R1" in request.uri


def test_cookies_tickets_and_tokens_removed_from_response():
    response = _scrub_response(
        {
            "headers": {
                "Set-Cookie": ["CASTGC_r1=TGT-1-secret; Path=/"],
                "Location": ["https://space.test/enovia?ticket=ST-2-secret"],
                "Content-Type": ["application/json"],
            },
            "body": {"string": b'{"lt":"LT-3","csrf":{"name":"ENO_CSRF_TOKEN","value":"tok-4"}}'},
        }
    )
    assert "Set-Cookie" not in response["headers"]
    assert response["headers"]["Location"] == ["https://space.test/enovia?ticket=REDACTED"]
    assert response["headers"]["Content-Type"] == ["application/json"]
    body = response["body"]["string"]
    assert b"LT-3" not in body and b"tok-4" not in body

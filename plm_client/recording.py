"""vcrpy setup that keeps credentials, cookies and tokens out of cassettes."""
import re
from pathlib import Path

import vcr

CASSETTE_DIR = Path(__file__).resolve().parents[1] / "tests" / "cassettes"

_BODY_SECRETS = [
    (re.compile(rb'("lt"\s*:\s*")[^"]*(")'), rb"\1REDACTED\2"),
    (re.compile(rb'("csrf"\s*:\s*\{[^}]*?"value"\s*:\s*")[^"]*(")'), rb"\1REDACTED\2"),
]
_CAS_TICKET = re.compile(r"ticket=[^&\s]+")


def _scrub_request(request):
    # Also applied to live requests during replay, so recorded and replayed URIs still match
    request.uri = _CAS_TICKET.sub("ticket=REDACTED", request.uri)
    return request


def _scrub_response(response: dict) -> dict:
    # filter_headers only covers request headers; session cookies (CASTGC, JSESSIONID) arrive here
    headers = response.get("headers", {})
    for name in list(headers):
        if name.lower() == "set-cookie":
            del headers[name]
        elif name.lower() == "location":
            values = headers[name] if isinstance(headers[name], list) else [headers[name]]
            headers[name] = [_CAS_TICKET.sub("ticket=REDACTED", v) for v in values]

    body = response["body"].get("string")
    if isinstance(body, str):
        body = body.encode()
    if body:
        for pattern, replacement in _BODY_SECRETS:
            body = pattern.sub(replacement, body)
        response["body"]["string"] = body
    return response


def recorder(record_mode: str) -> vcr.VCR:
    """record_mode "all" re-records against the tenant; "none" replays with no network."""
    return vcr.VCR(
        cassette_library_dir=str(CASSETTE_DIR),
        record_mode=record_mode,
        filter_headers=["Cookie", "Set-Cookie", "Authorization", "ENO_CSRF_TOKEN"],
        filter_post_data_parameters=["username", "password", "lt"],
        before_record_request=_scrub_request,
        before_record_response=_scrub_response,
        decode_compressed_response=True,
    )

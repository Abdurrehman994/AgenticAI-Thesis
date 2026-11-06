"""Serve the PLM Data Agent widget over HTTPS on this machine, for 3DDashboard's "Run your App" widget.

    python scripts/serve_widget.py                 # https://localhost:8443/index.html
    python scripts/serve_widget.py --port 9443

First open https://localhost:8443/index.html in the browser once and accept the self-signed certificate,
then paste the same URL into "Run your App". Opened directly (outside 3DDashboard), the widget runs on a
dataset instead of the tenant: the offline demo.

The widget talks to 3DSpace itself, with the logged-in user's session (WAFData): this server never sees the
user's password or PLM data. It only serves the widget files and the agent's side of the review:
- GET  /api/config        tenant URL, SecurityContext and collab space from .env (no credentials)
- GET  /api/pending       proposals awaiting review in runs/proposals.jsonl (part numbers live only there)
- POST /api/decision      record a decision the widget applied in PLM: {proposal_id, event, final_value}
- GET  /api/offline?dataset=dataset.json   an in-memory tenant for the offline demo, with rule proposals
Only pages from *.3dexperience.3ds.com and this server may call the API (CORS); it listens on 127.0.0.1 only.
"""
import argparse
import json
import os
import shutil
import ssl
import subprocess
import sys
from dataclasses import asdict
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.gaps import FIELDS, find_gaps  # noqa: E402
from agent.offline import DatasetTenant  # noqa: E402
from agent.snapshot import Snapshot  # noqa: E402
from agent.suggest import RuleBasedSuggester  # noqa: E402
from agent.writeback import ProposalLog, proposed_text  # noqa: E402
from plm_client.config import tenant_from_url  # noqa: E402

WIDGET = ROOT / "widget"
CERT_DIR = WIDGET / ".cert"
DATASETS = {"dataset.json", "dataset_cad.json"}
MIN_CONFIDENCE = 0.5  # as run_agent.py --apply: lower proposals are not written or logged
PLATFORM_SUFFIX = ".3dexperience.3ds.com"
OPENSSL_CANDIDATES = (r"C:\Program Files\Git\usr\bin\openssl.exe", r"C:\Program Files\Git\mingw64\bin\openssl.exe")


def offline_payload(dataset: dict) -> dict:
    """The dataset as the widget's snapshot, with the rule-based proposals "written" as run_agent.py --apply would."""
    tenant = DatasetTenant(dataset)
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    items = {item_id: dict(item) for item_id, item in snapshot.items.items()}
    suggester, pending = RuleBasedSuggester(), []
    for n, gap in enumerate(find_gaps(items.values(), fields=FIELDS)):
        proposal = suggester.suggest(gap, snapshot)
        if proposal is None or proposal.confidence < MIN_CONFIDENCE:
            continue
        record = {**asdict(proposal), "proposal_id": f"offline{n:02d}", "suggester": "rules",
                  "old_value": "", "written_to_plm": proposal.field == "description", "status": "pending"}
        if record["written_to_plm"]:
            items[proposal.item_id]["description"] = proposed_text(proposal.value)
        pending.append(record)
    return {"collabspace": dataset["collabspace"], "items": items,
            "children": {item_id: snapshot.children(item_id) for item_id in items}, "pending": pending}


def decision_record(body: dict, pending: list[dict]) -> dict:
    """The log record for a decision the widget made, or ValueError if it does not fit a pending proposal."""
    record = next((p for p in pending if p["proposal_id"] == body.get("proposal_id")), None)
    if record is None:
        raise ValueError(f"no pending proposal {body.get('proposal_id')!r}")
    if body.get("event") == "rejected":
        return {"event": "rejected", "proposal_id": record["proposal_id"], "via": "widget"}
    if body.get("event") != "approved":
        raise ValueError("event must be 'approved' or 'rejected'")
    final = body.get("final_value", record["value"])
    if not isinstance(final, str) or not final.strip():
        raise ValueError("an approved value cannot be empty: reject the proposal instead")
    return {"event": "approved", "proposal_id": record["proposal_id"], "final_value": final,
            "edited": final != record["value"], "via": "widget"}


def config() -> dict:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    space_url = os.getenv("PLM_SPACE_URL", "")
    context = os.getenv("PLM_SECURITY_CONTEXT", "")
    return {"spaceUrl": space_url, "securityContext": context,
            "collabspace": os.getenv("PLM_COLLABSPACE") or context.rsplit(".", 1)[-1],
            "tenant": os.getenv("PLM_TENANT") or tenant_from_url(space_url)}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WIDGET), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # edits to the widget show on the next reload
        origin = self.headers.get("Origin", "")
        host = urlparse(origin).hostname or ""
        if host.endswith(PLATFORM_SUFFIX) or host == "localhost":
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Private-Network", "true")  # Chrome: public page -> localhost
            self.send_header("Vary", "Origin")
        super().end_headers()

    def send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/config":
            return self.send_json(config())
        if url.path == "/api/pending":
            return self.send_json(ProposalLog().pending())
        if url.path == "/api/offline":
            name = parse_qs(url.query).get("dataset", ["dataset.json"])[0]
            if name not in DATASETS:
                return self.send_json({"error": f"dataset must be one of {sorted(DATASETS)}"}, HTTPStatus.BAD_REQUEST)
            return self.send_json(offline_payload(json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))))
        if url.path.startswith("/api/"):
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/decision":
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            log = ProposalLog()
            record = decision_record(body, log.pending())
        except (ValueError, json.JSONDecodeError) as e:
            return self.send_json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
        log.append(record)
        return self.send_json(record)


def certificate() -> tuple[Path, Path]:
    """A self-signed certificate for localhost, made once with openssl (Git for Windows ships one)."""
    cert, key = CERT_DIR / "localhost.pem", CERT_DIR / "localhost-key.pem"
    if cert.exists() and key.exists():
        return cert, key
    openssl = shutil.which("openssl") or next((p for p in OPENSSL_CANDIDATES if Path(p).exists()), None)
    if openssl is None:
        raise SystemExit("openssl not found: install Git for Windows or put openssl on PATH")
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365",
        "-keyout", str(key), "-out", str(cert), "-subj", "/CN=localhost",
        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
    ], check=True, capture_output=True)
    return cert, key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8443)
    args = parser.parse_args()

    cert, key = certificate()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    url = f"https://localhost:{args.port}/index.html"
    print(f"Serving {WIDGET} at {url}\n"
          f"1. Open {url} in this browser and accept the certificate warning (offline demo opens).\n"
          f"2. In 3DDashboard, paste {url} into 'Run your App'.\nCtrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Small local web application for departmental accounting."""

import json
import base64
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    from .accounting import AccountingDB, AccountingError
except ImportError:  # Allows `python src/app.py` as well as `python -m src.app`.
    from accounting import AccountingDB, AccountingError

DB = AccountingDB(Path(__file__).parent.parent / "data" / "accounting.db")
SESSIONS: dict[str, dict] = {}


class Handler(BaseHTTPRequestHandler):
    """Serve the accounting dashboard and JSON actions."""

    def send_json(self, payload: object, status: int = 200) -> None:
        """Send a JSON response."""
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def user(self) -> dict | None:
        """Return the authenticated session user, if present."""
        cookie = self.headers.get("Cookie", "")
        token = next((x.split("=", 1)[1] for x in cookie.split("; ") if x.startswith("session=")), "")
        return SESSIONS.get(token)

    def require_user(self) -> bool:
        """Reject unauthenticated API calls."""
        if not self.user(): self.send_json({"error": "Login required"}, 401); return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        """Handle dashboard and report requests."""
        path = urlparse(self.path).path
        if path == "/":
            body = (Path(__file__).parent / "static" / "index.html").read_bytes()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        elif path.startswith("/api/") and not self.require_user(): return
        elif path == "/api/dashboard": self.send_json(DB.dashboard())
        elif path == "/api/pending": self.send_json(DB.pending())
        elif path == "/api/students": self.send_json(DB.students())
        elif path == "/api/suppliers": self.send_json(DB.suppliers())
        elif path in {"/api/cash-book", "/api/ledger"}: self.send_json(DB.rows("cash" if "cash" in path else "ledger"))
        else: self.send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        """Handle validated voucher, student, and approval actions."""
        try:
            length = int(self.headers.get("Content-Length", 0)); data = json.loads(self.rfile.read(length) or b"{}")
            path = urlparse(self.path).path
            if path == "/api/login":
                user = DB.authenticate(data.get("name", ""), data.get("password", ""))
                if not user: self.send_json({"error": "Invalid clerk name or password"}, 401); return
                token = secrets.token_urlsafe(32); SESSIONS[token] = user
                result = user; self.send_response(200); self.send_header("Set-Cookie", f"session={token}; HttpOnly; SameSite=Strict; Path=/")
                body = json.dumps(result).encode(); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            elif not self.require_user(): return
            elif path == "/api/students": result = {"id": DB.add_student(data.get("student_no", ""), data.get("name", ""), data.get("department", ""))}
            elif path == "/api/suppliers": result = {"id": DB.add_supplier(data.get("name", ""), data.get("tax_number", ""), data.get("withholding_rate", 0))}
            elif path == "/api/uploads": result = DB.upload(data["filename"], data["kind"], base64.b64decode(data["content"]), self.user()["name"])
            elif path == "/api/vouchers": result = {"id": DB.create_voucher(data["voucher_type"], data.get("voucher_date", ""), data["description"], data["lines"], self.user()["name"], data.get("student_id"), data.get("supplier_id"))}
            elif path.startswith("/api/vouchers/") and path.endswith("/approve"): DB.approve_voucher(int(path.split("/")[3]), self.user()["name"]); result = {"ok": True}
            else: self.send_json({"error": "Not found"}, 404); return
            self.send_json(result, 201)
        except (AccountingError, KeyError, ValueError, json.JSONDecodeError) as exc: self.send_json({"error": str(exc)}, 400)


if __name__ == "__main__":
    print("Departmental Accounting: http://127.0.0.1:8000")
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
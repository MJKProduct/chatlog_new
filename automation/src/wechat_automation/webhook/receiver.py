from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

HandlerFactory = Callable[[dict], dict]


class _WebhookHandler(BaseHTTPRequestHandler):
    callback: Optional[HandlerFactory] = None

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"accepted":false,"reason":"invalid_json"}')
            return
        if _WebhookHandler.callback is None:
            self.send_response(503)
            self.end_headers()
            return
        result = _WebhookHandler.callback(body)
        code = 200 if result.get("accepted") else 422
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class LocalWebhookServer:
    """Loopback-only webhook receiver; not started unless explicitly requested."""

    def __init__(self, handler: HandlerFactory) -> None:
        self._handler = handler
        self._httpd: HTTPServer | None = None
        self.port = pick_free_port()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        _WebhookHandler.callback = self._handler
        self._httpd = HTTPServer(("127.0.0.1", self.port), _WebhookHandler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()

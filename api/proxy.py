"""Small Vercel gateway for the persistent VietLex FastAPI origin."""

from http.server import BaseHTTPRequestHandler
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


_HOP_BY_HOP = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


class handler(BaseHTTPRequestHandler):
    def _proxy(self) -> None:
        origin = os.getenv("BACKEND_ORIGIN", "").rstrip("/")
        parsed_origin = urlsplit(origin)
        if parsed_origin.scheme not in {"http", "https"} or not parsed_origin.netloc:
            self._json_error(503, "BACKEND_ORIGIN is not configured")
            return

        incoming = urlsplit(self.path)
        pairs = parse_qsl(incoming.query, keep_blank_values=True)
        target_path = ""
        forwarded_query = []
        for key, value in pairs:
            if key == "path" and not target_path:
                target_path = value
            else:
                forwarded_query.append((key, value))
        target = urlunsplit(
            (
                parsed_origin.scheme,
                parsed_origin.netloc,
                f"{parsed_origin.path.rstrip('/')}/{target_path.lstrip('/')}",
                urlencode(forwarded_query),
                "",
            )
        )
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in _HOP_BY_HOP
        }
        request = Request(target, data=body, headers=headers, method=self.command)
        try:
            with urlopen(request, timeout=115) as upstream:
                self._relay(upstream.status, upstream.headers, upstream.read())
        except HTTPError as exc:
            self._relay(exc.code, exc.headers, exc.read())
        except (URLError, TimeoutError):
            self._json_error(502, "VietLex backend is unavailable")

    def _relay(self, status, headers, body: bytes) -> None:
        self.send_response(status)
        for key, value in headers.items():
            if key.lower() not in _HOP_BY_HOP and key.lower() != "set-cookie":
                self.send_header(key, value)
        for cookie in headers.get_all("Set-Cookie", []):
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json_error(self, status: int, message: str) -> None:
        body = json.dumps({"detail": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _proxy

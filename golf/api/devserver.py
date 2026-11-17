"""Local preview: serves public/ and the golf API from one origin, like nginx does in production.

    GOLF_DATABASE_URL=postgresql://... python golf/api/devserver.py
    open http://127.0.0.1:8000/golf/

Development only: it uses the standard library server and turns off the Secure cookie flag.
"""
from __future__ import annotations

import mimetypes
import os
import sys
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

HERE = Path(__file__).resolve().parent
PUBLIC = HERE.parent.parent / "public"
sys.path.insert(0, str(HERE))
os.environ.setdefault("GOLF_COOKIE_SECURE", "0")
PORT = int(os.environ.get("GOLF_DEV_PORT", "8000"))
os.environ.setdefault("GOLF_ALLOWED_ORIGINS", f"http://127.0.0.1:{PORT},http://localhost:{PORT}")

import app  # noqa: E402

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")


def static(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    target = (PUBLIC / path.lstrip("/")).resolve()
    if PUBLIC not in target.parents and target != PUBLIC:
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"Not found"]
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"Not found"]
    body = target.read_bytes()
    kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    start_response("200 OK", [("Content-Type", kind), ("Content-Length", str(len(body))), ("Cache-Control", "no-cache")])
    return [body]


def dispatch(environ, start_response):
    if environ.get("PATH_INFO", "").startswith("/api/golf/"):
        return app.application(environ, start_response)
    return static(environ, start_response)


class ThreadingServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        if os.environ.get("GOLF_DEV_LOG"):
            super().log_message(format, *args)


if __name__ == "__main__":
    if not os.environ.get("GOLF_DATABASE_URL"):
        sys.exit("Set GOLF_DATABASE_URL first")
    with make_server("127.0.0.1", PORT, dispatch, server_class=ThreadingServer, handler_class=QuietHandler) as server:
        print(f"Golf preview on http://127.0.0.1:{PORT}/golf/", flush=True)
        server.serve_forever()

"""Deployment checks for the golf API: the pieces in deploy/ must agree with each other, setup must
fail loudly when the API doesn't answer, and the health check must recognise the real API."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


def read(name: str) -> str:
    return (DEPLOY / name).read_text(encoding="utf-8")


def load_check():
    spec = importlib.util.spec_from_file_location("golf_check", DEPLOY / "golf-check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeployWiring(unittest.TestCase):
    def test_service_nginx_and_checks_use_the_same_loopback_port(self):
        unit = read("golf-api.service")
        port = re.search(r"--bind 127\.0\.0\.1:(\d+)", unit).group(1)
        nginx = read("nginx-brettsbox.conf")
        api_block = nginx[nginx.index("location ^~ /api/golf/"):]
        self.assertIn(f"proxy_pass http://127.0.0.1:{port};", api_block)
        self.assertIn(f"http://127.0.0.1:{port}/api/golf/app", read("golf-deploy.sh"))
        self.assertIn(f":{port}", read("golf-doctor.sh"))

    def test_service_runs_the_deployed_copy_not_the_checkout(self):
        # The service user must never need access to /srv (where the checkout's permissions belong
        # to nginx), and git updates must not change files under running workers.
        unit = read("golf-api.service")
        workdir = re.search(r"^WorkingDirectory=(.+)$", unit, re.M).group(1)
        self.assertEqual(workdir, "/opt/brettsbox-golf/api")
        deploy = read("golf-deploy.sh")
        self.assertIn("local app=/opt/brettsbox-golf", deploy)
        self.assertIn('mv "$app/api.new" "$app/api"', deploy)
        self.assertNotIn("/srv/", unit)

    def test_setup_fails_loudly_unless_the_api_answers_through_nginx(self):
        setup = read("setup.sh")
        line = next(l for l in setup.splitlines() if "golf-setup.sh" in l and not l.lstrip().startswith("#"))
        self.assertNotIn("||", line, "a golf failure must fail setup.sh")
        golf = read("golf-setup.sh")
        self.assertIn('bash "$repo/deploy/golf-deploy.sh"', golf)
        # nginx is applied after the API is up, then checked end to end.
        self.assertLess(golf.index("golf-deploy.sh"), golf.index("nginx-apply.sh"))
        self.assertIn("--host brettsbox.com", golf)
        self.assertIn("golf-doctor.sh", golf)

    def test_nginx_changes_are_applied_with_a_restart_when_a_reload_cannot(self):
        # The live failure: nginx kept the original `listen 80` config because a reload can't swap
        # 0.0.0.0:80 for 127.0.0.1:80, and `systemctl reload` reported success anyway.
        self.assertIn("bash /srv/brettsbox/deploy/nginx-apply.sh", read("setup.sh"))
        self.assertNotIn("systemctl reload nginx", read("setup.sh"))
        apply = read("nginx-apply.sh")
        detect = apply[apply.index("ss -Hltn"):]
        self.assertIn(r"grep -qvE '^(127\.0\.0\.1|\[::1\]):80$'", detect)
        self.assertLess(detect.index("systemctl restart nginx"), detect.index("systemctl reload nginx"))
        listens = re.findall(r"^\s*listen\s+(\S+)", read("nginx-brettsbox.conf"), re.M)
        self.assertEqual(listens, ["127.0.0.1:80", "[::1]:80"])

    def test_scripts_are_read_in_full_before_they_run(self):
        # setup.sh resets the checkout it runs from; bash must not read the replaced file midway.
        for name in ("setup.sh", "golf-setup.sh", "golf-deploy.sh", "nginx-apply.sh"):
            text = read(name).rstrip()
            self.assertTrue(text.endswith('main "$@"\nexit'), name)

    def test_nginx_routes_golf_before_the_static_site(self):
        nginx = read("nginx-brettsbox.conf")
        self.assertLess(nginx.index("location ^~ /api/golf/"), nginx.index("location / {"))
        golf_block = nginx[nginx.index("location ^~ /golf/"):nginx.index("location / {")]
        self.assertIn('Cache-Control "no-cache"', golf_block)


class Handler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, str, bytes]] = {}

    def do_GET(self):
        status, kind, body = self.routes.get(self.path, (404, "text/html", b"<h1>Page not found</h1>"))
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class HealthCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.check = staticmethod(load_check().check)
        Handler.routes = {
            "/api/golf/app": (200, "application/json", json.dumps({"course": {}, "user": None}).encode()),
            "/api/golf/broken": (500, "application/json", b'{"error":"Something went wrong"}'),
        }
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_accepts_the_golf_api(self):
        self.assertIsNone(self.check(f"{self.base}/api/golf/app", None))

    def test_rejects_the_static_site_404_page(self):
        # What https://brettsbox.com/api/golf/app returned while nginx still had the old config.
        problem = self.check(f"{self.base}/api/golf/missing", "brettsbox.com")
        self.assertIn("HTTP 404", problem)

    def test_reports_api_errors(self):
        self.assertIn("HTTP 500", self.check(f"{self.base}/api/golf/broken", None))

    def test_ignores_proxy_settings_for_the_local_check(self):
        saved = {key: os.environ.get(key) for key in ("http_proxy", "HTTP_PROXY", "no_proxy", "NO_PROXY")}
        os.environ.update(http_proxy="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9", no_proxy="", NO_PROXY="")
        try:
            self.assertIsNone(self.check(f"{self.base}/api/golf/app", None))
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()

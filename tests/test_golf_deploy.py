"""Deployment wiring and executable health/listener regression checks (no root required)."""
from __future__ import annotations

import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
APP = {"course": {"name": "Golf"}, "today": "2026-11-17", "now": "2026-11-17T09:00:00Z", "user": None}


class HealthCheck(unittest.TestCase):
    def check_response(self, body, content_type="application/json", status=200, wait=0):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                # Even loopback must ignore proxies, including when no_proxy is empty.
                env = dict(os.environ, http_proxy="http://127.0.0.1:1",
                           HTTP_PROXY="http://127.0.0.1:1", no_proxy="", NO_PROXY="")
                return subprocess.run(
                    [sys.executable, str(DEPLOY / "golf-health.py"), "--wait", str(wait),
                     f"http://127.0.0.1:{server.server_port}/api/golf/app"],
                    env=env, capture_output=True, text=True, timeout=5,
                )
            finally:
                server.shutdown()
                thread.join()

    def test_api_answer_ignores_proxy(self):
        result = self.check_response(json.dumps(APP).encode())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_live_site_404_page_is_not_an_api_answer(self):
        result = self.check_response((ROOT / "public" / "404.html").read_bytes(), "text/html", 404)
        self.assertNotEqual(result.returncode, 0)

    def test_html_success_is_not_an_api_answer(self):
        self.assertNotEqual(self.check_response(b"<html>not the API</html>", "text/html").returncode, 0)

    def test_json_error_or_unrelated_json_is_not_an_api_answer(self):
        for body in (b'{"error":"unavailable"}', b"[]", b"null", b"{broken"):
            with self.subTest(body=body):
                self.assertNotEqual(self.check_response(body).returncode, 0)

    def test_wait_expires_on_unhealthy_response(self):
        self.assertNotEqual(self.check_response(b"{}", wait=0.1).returncode, 0)


class NginxApply(unittest.TestCase):
    def apply(self, listeners, active=True):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            log = path / "commands"
            commands = {
                "install": 'echo install >>"$COMMAND_LOG"',
                "ln": ":",
                "rm": ":",
                "nginx": 'echo "nginx $*" >>"$COMMAND_LOG"',
                "ss": 'printf "%s\\n" "$LISTENERS"',
                "systemctl": 'echo "systemctl $*" >>"$COMMAND_LOG"\n'
                             'if [ "$1" = is-active ]; then exit "$ACTIVE_STATUS"; fi',
            }
            for name, script in commands.items():
                command = path / name
                command.write_text("#!/bin/sh\n" + script + "\n")
                command.chmod(0o755)
            result = subprocess.run(
                ["bash", str(DEPLOY / "nginx-apply.sh")],
                env=dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"],
                         COMMAND_LOG=str(log), LISTENERS=listeners, ACTIVE_STATUS="0" if active else "3"),
                capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = log.read_text().splitlines()
            self.assertLess(lines.index("nginx -t"), len(lines) - 1)
            return lines[-1]

    def test_wildcard_or_nonloopback_listener_requires_restart(self):
        for address in ("0.0.0.0:80", "[::]:80", "*:80", "192.168.1.140:80"):
            with self.subTest(address=address):
                self.assertEqual(self.apply(f"LISTEN 0 511 {address} 0.0.0.0:*"), "systemctl restart nginx")

    def test_loopback_only_listeners_reload(self):
        self.assertEqual(self.apply("LISTEN 0 511 127.0.0.1:80 0.0.0.0:*\n"
                                    "LISTEN 0 511 [::1]:80 [::]:*"), "systemctl reload nginx")

    def test_stopped_nginx_is_started(self):
        self.assertEqual(self.apply("", active=False), "systemctl restart nginx")


class DeployWiring(unittest.TestCase):
    def test_setup_and_timer_share_locked_deployment(self):
        for filename in ("golf-setup.sh", "brettsbox-pull.sh"):
            self.assertIn("deploy/golf-deploy.sh", (DEPLOY / filename).read_text())
        script = (DEPLOY / "golf-deploy.sh").read_text()
        self.assertLess(script.index("flock -x"), script.index("systemctl stop"))
        self.assertIn('cp -R "$repo/golf/api" "$app_dir/api.new"', script)
        self.assertIn('chmod -R u=rwX,go=rX "$app_dir/api.new"', script)
        self.assertIn('"$app_dir/api.new/migrate.py"', script)
        self.assertLess(script.index('"$app_dir/api.new/migrate.py"'), script.index("systemctl stop"))
        self.assertIn('mv "$app_dir/api.new" "$app_dir/api"', script)
        self.assertLess(script.index("--wait 45"), script.index('>"$app_dir/deployed"'))
        self.assertIn("WorkingDirectory=/opt/brettsbox-golf/api", (DEPLOY / "golf-api.service").read_text())
        for filename in ("setup.sh", "brettsbox-pull.sh"):
            updater = (DEPLOY / filename).read_text()
            self.assertIn("exec 9>/run/brettsbox-golf-deploy.lock", updater)
            self.assertLess(updater.index("flock -x 9"), updater.index("reset -q --hard"))
            self.assertLess(updater.index("reset -q --hard"), updater.index("flock -u 9"))
        self.assertIn("exec 9>/run/brettsbox-golf-deploy.lock", script)
        self.assertLess(script.index('rm -f "$app_dir/deployed"'), script.index("systemctl stop"))

    def test_setup_applies_nginx_after_api_and_checks_proxy(self):
        for filename in ("setup.sh", "golf-setup.sh"):
            self.assertIn("deploy/nginx-apply.sh", (DEPLOY / filename).read_text())
        script = (DEPLOY / "golf-setup.sh").read_text()
        self.assertLess(script.index("deploy/golf-deploy.sh"), script.index("deploy/nginx-apply.sh"))
        self.assertIn("http://127.0.0.1/api/golf/app", script)
        self.assertIn("systemctl restart nginx", script)
        self.assertIn("--encoding=UTF8 --template=template0", script)
        for filename in ("setup.sh", "golf-setup.sh", "brettsbox-pull.sh", "golf-deploy.sh", "nginx-apply.sh"):
            script = (DEPLOY / filename).read_text()
            self.assertIn("main() {", script)
            self.assertTrue(script.rstrip().endswith('main "$@"; exit'))
            self.assertIn("golf-doctor.sh", script)
            self.assertIn("set -Eeuo pipefail", script)
        self.assertNotIn('|| echo "Golf setup', (DEPLOY / "setup.sh").read_text())


if __name__ == "__main__":
    unittest.main()

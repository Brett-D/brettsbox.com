"""Checks on the golf PWA files: installability, offline shell, touch targets, themes and the
static-site build leaving the app alone."""
from __future__ import annotations

import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLF = ROOT / "public" / "golf"


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    return struct.unpack(">II", data[16:24])


class InstallableApp(unittest.TestCase):
    def test_manifest_is_a_standalone_app_with_png_icons(self):
        manifest = json.loads((GOLF / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual((manifest["start_url"], manifest["scope"], manifest["display"]), ("/golf/", "/golf/", "standalone"))
        sizes = {icon["sizes"]: icon for icon in manifest["icons"] if icon["type"] == "image/png"}
        for size in ("192x192", "512x512"):
            width, height = png_size(ROOT / "public" / sizes[size]["src"].lstrip("/"))
            self.assertEqual(f"{width}x{height}", size)
        self.assertTrue(any(icon.get("purpose") == "maskable" for icon in manifest["icons"]))

    def test_ipad_home_screen_metadata(self):
        html = (GOLF / "index.html").read_text(encoding="utf-8")
        self.assertIn("viewport-fit=cover", html)
        self.assertIn('name="apple-mobile-web-app-capable" content="yes"', html)
        self.assertEqual(png_size(GOLF / "icons" / "apple-touch-icon.png"), (180, 180))
        # theme.js must run before the stylesheet paints anything.
        self.assertLess(html.index("/golf/theme.js"), html.index("/golf/style.css"))
        self.assertNotIn("<script>", html)  # the CSP allows no inline script

    def test_service_worker_caches_the_shell_but_never_the_api(self):
        sw = (GOLF / "sw.js").read_text(encoding="utf-8")
        shell = re.search(r"const SHELL = \[(.*?)\];", sw, re.S).group(1)
        for asset in re.findall(r'"([^"]+)"', shell):
            self.assertTrue((ROOT / "public" / asset.lstrip("/")).exists() or asset == "/golf/", f"{asset} is missing")
        self.assertNotIn("/api/", shell)
        self.assertIn("!inShell) return;", sw)  # API requests are never intercepted or cached


class TouchAndThemes(unittest.TestCase):
    css = (GOLF / "style.css").read_text(encoding="utf-8")

    def test_touch_targets_and_no_hover_only_actions(self):
        self.assertIn("--tap: 48px", self.css)
        self.assertIn("--tap: 52px", self.css)  # bigger still on touch screens
        hover_rules = re.findall(r"([^{}]*:hover[^{]*)\{", self.css)
        self.assertTrue(hover_rules)
        hover_block = self.css[self.css.index("@media (hover: hover) and (pointer: fine)"):]
        for rule in hover_rules:
            self.assertIn(rule.strip(), hover_block, "hover styles must only polish mouse use")

    def test_light_and_dark_palettes_define_the_same_tokens(self):
        light = self.css[self.css.index(":root {"):self.css.index(':root[data-theme="dark"]')]
        dark = self.css[self.css.index(':root[data-theme="dark"]'):self.css.index("@media (prefers-color-scheme: dark)")]
        auto = self.css[self.css.index("@media (prefers-color-scheme: dark)"):self.css.index("/* ====")]
        colour_tokens = lambda block: set(re.findall(r"(--[a-z0-9-]+):", block))  # noqa: E731
        themed = colour_tokens(dark)
        self.assertGreater(len(themed), 40)
        self.assertLessEqual(themed, colour_tokens(light))
        self.assertEqual(themed, colour_tokens(auto))
        self.assertIn('localStorage.getItem("golf-theme")', (GOLF / "theme.js").read_text(encoding="utf-8"))

    def test_app_markup_uses_no_inline_styles(self):
        app = (GOLF / "app.js").read_text(encoding="utf-8")
        self.assertNotRegex(app, r'style="', "inline style attributes would be blocked by the CSP")


class SiteBuild(unittest.TestCase):
    def test_static_build_keeps_the_golf_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "preview"
            subprocess.run([sys.executable, str(ROOT / "site" / "build.py"), "--out", str(out)], check=True,
                           capture_output=True)
            self.assertTrue((out / "golf" / "index.html").exists())
            self.assertTrue((out / "lab" / "index.html").exists())
            self.assertTrue((out / "blueprint" / "index.html").exists())


if __name__ == "__main__":
    unittest.main()

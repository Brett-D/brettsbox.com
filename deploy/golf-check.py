"""Wait for the golf API to answer, then exit 0; exit 1 with the last error after a timeout.

    python deploy/golf-check.py http://127.0.0.1:8787/api/golf/app [--host brettsbox.com] [--timeout 45]

Ignores http_proxy/HTTPS_PROXY settings: this always talks to the local machine directly.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def check(url: str, host: str | None) -> str | None:
    """None when the API answered properly, otherwise what went wrong."""
    request = urllib.request.Request(url, headers={"Host": host} if host else {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=3) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode("utf-8", "replace").strip()
        return f"HTTP {exc.code} from {url}: {detail}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return f"{url}: {exc}"
    if not isinstance(body, dict) or "course" not in body:
        return f"{url} answered, but not like the golf API: {str(body)[:200]}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--host")
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    problem = "never checked"
    while time.monotonic() < deadline:
        problem = check(args.url, args.host)
        if problem is None:
            return 0
        time.sleep(1.5)
    print(f"Golf API check failed: {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

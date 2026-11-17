#!/usr/bin/env python3
"""Check for a real golf API response, never via an environment-configured proxy."""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--wait", type=float, default=0)
    args = parser.parse_args()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + max(0, args.wait)
    while True:
        try:
            request = urllib.request.Request(args.url, headers={"Host": "brettsbox.com"})
            timeout = min(3, max(0.1, deadline - time.monotonic())) if args.wait > 0 else 3
            with opener.open(request, timeout=timeout) as response:
                if response.status != 200 or response.headers.get_content_type() != "application/json":
                    raise ValueError("expected HTTP 200 application/json")
                data = json.load(response)
                if not (isinstance(data, dict) and isinstance(data.get("course"), dict)
                        and isinstance(data.get("today"), str) and "now" in data and "user" in data):
                    raise ValueError("response is not the golf app API")
            return 0
        except (OSError, ValueError, urllib.error.URLError) as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print(f"{args.url}: {exc}", file=sys.stderr)
                return 1
            time.sleep(min(1, remaining))


if __name__ == "__main__":
    sys.exit(main())

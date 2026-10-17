"""Serve the app against the STAGING Supabase project. For trying the UI on a phone on the same Wi-Fi.

Reads .env.staging (never .env), refuses the live project, and binds 0.0.0.0 so a phone can reach it.
Nothing secret is printed: the project ref, the port and the URLs to open.

Usage:
  ./.venv/bin/python scripts/serve_staging.py               # port 8765, all interfaces
  ./.venv/bin/python scripts/serve_staging.py --port 8765
  ./.venv/bin/python scripts/serve_staging.py --host 127.0.0.1

Stop it with Ctrl-C in the terminal it runs in (see the README notes if it was backgrounded).
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path

from dotenv import dotenv_values

REPO = Path(__file__).resolve().parents[1]
ENV_FILE = REPO / ".env.staging"
LIVE_PROJECT_REF = "viorpltdkpexswvofeul"
STAGING_PROJECT_REF = "tddigsmukmhkjrwiqdec"


def project_ref(url: str) -> str | None:
    host = (url or "").split("//")[-1].split("/")[0]
    return host.split(".")[0] if host.endswith(".supabase.co") else None


def lan_ip() -> str:
    """The address this Mac would use on the local network. Needs no traffic to be sent."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 80))   # TEST-NET-1: nothing is actually sent
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="0.0.0.0", help="interface to bind (0.0.0.0 lets a phone in)")
    parser.add_argument("--port", type=int, default=8765, help="port to listen on (default 8765)")
    args = parser.parse_args()

    if not ENV_FILE.exists():
        print(f"missing {ENV_FILE}", file=sys.stderr)
        return 2
    values = {k: v for k, v in dotenv_values(ENV_FILE).items() if v is not None}
    ref = project_ref(values.get("SUPABASE_URL", ""))
    if ref == LIVE_PROJECT_REF:
        print("refused: .env.staging points at the LIVE project", file=sys.stderr)
        return 2
    if ref != STAGING_PROJECT_REF:
        print("refused: .env.staging does not point at the staging project", file=sys.stderr)
        return 2

    # The app reads the environment; the app's own .env loading will not override values already set.
    os.environ.update(values)
    os.environ.pop("ALLOW_LEGACY_API_KEY", None)   # the web UI signs in; the legacy key is for the Shortcut
    os.environ.pop("RENDER_GIT_COMMIT", None)      # so the Build row reads "dev" locally
    os.chdir(REPO)
    sys.path.insert(0, str(REPO))

    ip = lan_ip()
    print()
    print(f"  project : staging ({ref})")
    print(f"  port    : {args.port}  (bound to {args.host})")
    print(f"  on this Mac : http://127.0.0.1:{args.port}/")
    if args.host == "0.0.0.0":
        print(f"  on your iPhone (same Wi-Fi) : http://{ip}:{args.port}/")
    print()
    print("  stop with Ctrl-C")
    print()
    sys.stdout.flush()

    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

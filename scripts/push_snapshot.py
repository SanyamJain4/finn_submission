"""Capture a live snapshot on this machine and push it to a hosted FINN, with no git commit or redeploy.

NSE and BSE block cloud IPs, so the hosted server can't fetch filings itself. Run this on a machine they don't block
(your laptop), by hand or on a schedule:

    cd backend
    python ../scripts/push_snapshot.py --url https://finn-iljw.onrender.com        # capture, then push
    python ../scripts/push_snapshot.py --skip-capture                              # push what is already on disk
    python ../scripts/push_snapshot.py --no-reports                                # quicker: skip research reports

The URL and token can also come from FINN_INGEST_URL / FINN_INGEST_TOKEN in the environment or the repo's .env.
The server must have the same FINN_INGEST_TOKEN set, otherwise /api/ingest is switched off.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "data" / "snapshot"


def _env_file() -> dict[str, str]:
    p = ROOT / ".env"
    out = {}
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def collect() -> dict:
    files = {}
    for p in OUT.rglob("*.json"):
        files[p.relative_to(OUT).as_posix()] = json.loads(p.read_text(encoding="utf-8"))
    return files


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="hosted FINN base URL")
    ap.add_argument("--skip-capture", action="store_true", help="push the files already in backend/data/snapshot")
    ap.add_argument("--no-reports", action="store_true", help="pass through to make_snapshot.py")
    ap.add_argument("--days", type=int, help="pass through to make_snapshot.py")
    a = ap.parse_args()
    cfg = {**_env_file(), **os.environ}
    url = (a.url or cfg.get("FINN_INGEST_URL", "")).rstrip("/")
    token = cfg.get("FINN_INGEST_TOKEN", "")
    if not url or not token:
        sys.exit("Need a URL (--url or FINN_INGEST_URL) and FINN_INGEST_TOKEN.")

    if not a.skip_capture:
        cmd = [sys.executable, str(ROOT / "scripts" / "make_snapshot.py")]
        if a.no_reports:
            cmd.append("--no-reports")
        if a.days:
            cmd += ["--days", str(a.days)]
        # make_snapshot exits non-zero without writing anything when this machine is blocked too
        if subprocess.run(cmd, cwd=ROOT / "backend").returncode != 0:
            sys.exit("Capture failed; nothing pushed.")

    files = collect()
    print(f"Pushing {len(files)} files ({sum(len(json.dumps(v)) for v in files.values()) / 1024:,.0f} KB) to {url}")
    last = ""
    for attempt in range(1, 4):  # the free host may be asleep; the first try wakes it
        try:
            r = httpx.post(f"{url}/api/ingest", json={"files": files}, headers={"X-Ingest-Token": token}, timeout=180)
            if r.status_code == 200:
                print("OK:", r.json())
                return
            last = f"HTTP {r.status_code}: {r.text[:300]}"
            if r.status_code in (400, 401, 404, 413):  # retrying won't help
                break
        except httpx.HTTPError as e:
            last = type(e).__name__
        print(f"attempt {attempt} failed ({last})")
        time.sleep(20)
    sys.exit(f"Push failed: {last}")


if __name__ == "__main__":
    main()

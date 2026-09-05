#!/usr/bin/env python3
"""E2E provisioning helper: create scratch layout DB, org tokens, warehouses.

Usage (run with backend/.venv311/bin/python, cwd = repo root or backend/):
  provision.py --org NAME            provision org + fresh token + warehouse w/ empty_layout(40,30,8)
  provision.py --org NAME --revoke TOKEN   revoke TOKEN (isolation spec T5)
  provision.py --revoke TOKEN             revoke TOKEN only

Prints one JSON object to stdout: {"token","warehouse_id","revision_id","org"}
(with --revoke: {"revoked": true}). Tokens appear ONLY in this stdout, never in logs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # .../frontend/e2e/helpers -> repo root
sys.path.insert(0, str(ROOT / "backend"))

from app.layout_geometry import empty_layout  # noqa: E402
from app.layout_store import LayoutStore  # noqa: E402

DB = "/tmp/e2e_l.db"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--org", default=None)
    p.add_argument("--revoke", metavar="TOKEN", default=None)
    args = p.parse_args()
    if args.revoke:
        store = LayoutStore(DB)
        store.revoke_access(args.revoke)
        print(json.dumps({"revoked": True}))
        return
    if not args.org:
        p.error("--org is required unless --revoke is given")
    store = LayoutStore(DB)
    token = store.issue_access(args.org, "qa-e2e")
    # idempotent: each Playwright worker runs beforeAll, so an org may already have
    # its warehouse from the other worker. Reuse the first one instead of duplicating.
    existing = store.list_warehouses(args.org)
    if existing:
        # fetch the org's revision list to get a usable revision id
        revisions = store.list_revisions(args.org, existing[0]["id"])
        revision = {"warehouse_id": existing[0]["id"], "id": revisions[0]["id"]}
    else:
        revision = store.create(args.org, f"{args.org} warehouse", empty_layout(f"{args.org} warehouse", 40, 30, 8))
    print(json.dumps({
        "token": token,
        "warehouse_id": revision["warehouse_id"],
        "revision_id": revision["id"],
        "org": args.org,
    }))


if __name__ == "__main__":
    main()

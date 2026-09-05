"""Tenant-scoped simulation runs pinned to immutable published revisions."""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from app.layout_store import LayoutNotFound, LayoutStore


ACTIVE, PAUSED, IDLE_PAUSED, ENDED = 'active', 'paused', 'idle_paused', 'ended'
_TRANSITIONS = {ACTIVE: {PAUSED, IDLE_PAUSED, ENDED}, PAUSED: {ACTIVE, ENDED},
                IDLE_PAUSED: {ACTIVE, ENDED}, ENDED: set()}


class RunInvalid(ValueError):
    pass


class LayoutRuns:
    """Run entities live in the SAME SQLite file as the layout store (TWIN_LAYOUT_DB)."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self.store = LayoutStore(path)  # ensures schema exists
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS layout_runs (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    warehouse_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    settings TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','paused','idle_paused','ended')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_active_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS layout_run_owner
                    ON layout_runs(organization_id, warehouse_id);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def _owned(self, db, organization_id, warehouse_id):
        row = db.execute('SELECT id FROM layout_warehouses WHERE id=? AND organization_id=?',
                         (warehouse_id, organization_id)).fetchone()
        if row is None:
            raise LayoutNotFound('Warehouse not found')

    def _get(self, db, organization_id, run_id):
        row = db.execute('SELECT * FROM layout_runs WHERE id=? AND organization_id=?',
                         (run_id, organization_id)).fetchone()
        if row is None:
            raise LayoutNotFound('Run not found')
        return row

    def create(self, organization_id: str, warehouse_id: str, revision_id: str,
               name: str, settings: dict, *, now: float | None = None) -> dict:
        if not name or not str(name).strip():
            raise ValueError('Run name is required')
        if not isinstance(settings, dict):
            raise ValueError('Run settings must be an object')
        try:
            encoded = json.dumps(settings, allow_nan=False, separators=(',', ':'))
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Run settings are not serializable: {exc}') from exc
        ts = time.time() if now is None else now
        run_id = uuid.uuid4().hex
        with self.connection() as db:
            self._owned(db, organization_id, warehouse_id)
            rev = db.execute("SELECT state FROM layout_revisions WHERE id=? AND warehouse_id=?",
                             (revision_id, warehouse_id)).fetchone()
            if rev is None:
                raise LayoutNotFound('Revision not found')
            if rev['state'] != 'published':
                raise RunInvalid('Runs must reference a published revision')
            db.execute(
                'INSERT INTO layout_runs(id,organization_id,warehouse_id,revision_id,name,settings,status,last_active_at)'
                ' VALUES(?,?,?,?,?,?,?,?)',
                (run_id, organization_id, warehouse_id, revision_id,
                 str(name).strip(), encoded, ACTIVE, ts))
        return self.get(organization_id, run_id)

    def get(self, organization_id: str, run_id: str) -> dict:
        with self.connection() as db:
            row = self._get(db, organization_id, run_id)
            result = dict(row)
            result['settings'] = json.loads(result['settings'])
            return result

    def list(self, organization_id: str, warehouse_id: str) -> list[dict]:
        with self.connection() as db:
            self._owned(db, organization_id, warehouse_id)
            rows = db.execute(
                'SELECT * FROM layout_runs WHERE organization_id=? AND warehouse_id=?'
                ' ORDER BY created_at,id', (organization_id, warehouse_id)).fetchall()
            out = []
            for row in rows:
                r = dict(row)
                r['settings'] = json.loads(r['settings'])
                out.append(r)
            return out

    def update_activity(self, organization_id: str, run_id: str,
                        *, now: float | None = None, idle_threshold_s: float = 900.0) -> dict:
        ts = time.time() if now is None else now
        with self.connection() as db:
            row = self._get(db, organization_id, run_id)
            if row['status'] == ACTIVE and ts - row['last_active_at'] > idle_threshold_s:
                db.execute("UPDATE layout_runs SET status='idle_paused', updated_at=CURRENT_TIMESTAMP,"
                           ' last_active_at=? WHERE id=?', (ts, run_id))
            elif row['status'] in (ACTIVE, PAUSED, IDLE_PAUSED):
                db.execute('UPDATE layout_runs SET last_active_at=?, updated_at=CURRENT_TIMESTAMP'
                           ' WHERE id=?', (ts, run_id))
        return self.get(organization_id, run_id)

    def _transition(self, organization_id: str, run_id: str, new_status: str) -> dict:
        with self.connection() as db:
            row = self._get(db, organization_id, run_id)
            if new_status not in _TRANSITIONS.get(row['status'], set()):
                raise RunInvalid(f'Cannot change run from {row["status"]} to {new_status}')
            db.execute('UPDATE layout_runs SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                       (new_status, run_id))
        return self.get(organization_id, run_id)

    def pause(self, organization_id: str, run_id: str) -> dict:
        return self._transition(organization_id, run_id, PAUSED)

    def resume(self, organization_id: str, run_id: str) -> dict:
        return self._transition(organization_id, run_id, ACTIVE)

    def end(self, organization_id: str, run_id: str) -> dict:
        return self._transition(organization_id, run_id, ENDED)

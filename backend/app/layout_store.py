"""Tenant-scoped layout persistence; callers supply authenticated organization IDs."""
from __future__ import annotations

import json
import sqlite3
import uuid
import hashlib
import secrets
import time
from contextlib import contextmanager
from pathlib import Path

from .layout_geometry import validate_geometry
from .layout_validation import validate_layout


class LayoutNotFound(LookupError):
    pass


class LayoutConflict(ValueError):
    pass


class LayoutInvalid(ValueError):
    def __init__(self, issues):
        super().__init__('Layout validation failed')
        self.issues = issues


class LayoutStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS layout_access_tokens (
                    digest TEXT PRIMARY KEY, organization_id TEXT NOT NULL,
                    user_id TEXT NOT NULL, expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS layout_warehouses (
                    id TEXT PRIMARY KEY, organization_id TEXT NOT NULL,
                    name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS layout_warehouse_owner
                    ON layout_warehouses(organization_id);
                CREATE TABLE IF NOT EXISTS layout_revisions (
                    id TEXT PRIMARY KEY,
                    warehouse_id TEXT NOT NULL REFERENCES layout_warehouses(id),
                    state TEXT NOT NULL CHECK(state IN ('draft', 'published')),
                    version INTEGER NOT NULL DEFAULT 1,
                    document TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TRIGGER IF NOT EXISTS layout_published_no_update
                BEFORE UPDATE ON layout_revisions WHEN OLD.state = 'published'
                BEGIN SELECT RAISE(ABORT, 'published revision is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS layout_published_no_delete
                BEFORE DELETE ON layout_revisions WHEN OLD.state = 'published'
                BEGIN SELECT RAISE(ABORT, 'published revision is immutable'); END;
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

    @staticmethod
    def _encode(document: dict) -> str:
        if not isinstance(document, dict):
            raise ValueError('Layout document must be an object')
        return json.dumps(document, allow_nan=False, separators=(',', ':'))

    def issue_access(self, organization_id: str, user_id: str, lifetime: int = 86400) -> str:
        """Administrative provisioning only; never exposed as a public route."""
        if not organization_id or not user_id or lifetime <= 0:
            raise ValueError('Organization, user and positive lifetime required')
        token = secrets.token_urlsafe(32)
        with self.connection() as db:
            db.execute('INSERT INTO layout_access_tokens VALUES(?,?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), organization_id,
                        user_id, time.time() + lifetime))
        return token

    def authenticate(self, token: str) -> dict | None:
        if not token or len(token) > 256:
            return None
        with self.connection() as db:
            row = db.execute('SELECT organization_id,user_id FROM layout_access_tokens WHERE digest=? AND expires_at>?',
                             (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
            return dict(row) if row else None

    def revoke_access(self, token: str) -> None:
        with self.connection() as db:
            db.execute('DELETE FROM layout_access_tokens WHERE digest=?',
                       (hashlib.sha256(token.encode()).hexdigest(),))

    def list_revisions(self, organization_id: str, warehouse_id: str) -> list[dict]:
        with self.connection() as db:
            self._owned(db, organization_id, warehouse_id)
            return [dict(row) for row in db.execute(
                'SELECT id,state,version,created_at FROM layout_revisions WHERE warehouse_id=? ORDER BY created_at,id',
                (warehouse_id,),
            )]

    @staticmethod
    def _owned(db, organization_id, warehouse_id):
        row = db.execute(
            'SELECT * FROM layout_warehouses WHERE id=? AND organization_id=?',
            (warehouse_id, organization_id),
        ).fetchone()
        if row is None:
            raise LayoutNotFound('Warehouse not found')
        return row

    def create(self, organization_id: str, name: str, document: dict) -> dict:
        if not organization_id or not name.strip():
            raise ValueError('Organization and warehouse name are required')
        encoded = self._encode(document)
        warehouse_id, revision_id = uuid.uuid4().hex, uuid.uuid4().hex
        with self.connection() as db:
            db.execute('INSERT INTO layout_warehouses(id,organization_id,name) VALUES(?,?,?)',
                       (warehouse_id, organization_id, name.strip()))
            db.execute('INSERT INTO layout_revisions(id,warehouse_id,state,document) VALUES(?,?,?,?)',
                       (revision_id, warehouse_id, 'draft', encoded))
        return self.get_revision(organization_id, warehouse_id, revision_id)

    def list_warehouses(self, organization_id: str) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                'SELECT id,name,created_at FROM layout_warehouses WHERE organization_id=? ORDER BY created_at,id',
                (organization_id,),
            )]

    def get_revision(self, organization_id: str, warehouse_id: str, revision_id: str) -> dict:
        with self.connection() as db:
            self._owned(db, organization_id, warehouse_id)
            row = db.execute('SELECT * FROM layout_revisions WHERE warehouse_id=? AND id=?',
                             (warehouse_id, revision_id)).fetchone()
            if row is None:
                raise LayoutNotFound('Revision not found')
            result = dict(row)
            result['document'] = json.loads(result['document'])
            return result

    def save_draft(self, organization_id: str, warehouse_id: str, revision_id: str,
                   expected_version: int, document: dict) -> dict:
        encoded = self._encode(document)
        with self.connection() as db:
            self._owned(db, organization_id, warehouse_id)
            changed = db.execute("""UPDATE layout_revisions SET document=?, version=version+1
                WHERE id=? AND warehouse_id=? AND state='draft' AND version=?""",
                (encoded, revision_id, warehouse_id, expected_version)).rowcount
            if changed != 1:
                raise LayoutConflict('Draft changed, is published, or does not exist')
            # Return this write's version, not a later writer's document read
            # through a new connection after the transaction commits.
            row = db.execute('SELECT * FROM layout_revisions WHERE id=? AND warehouse_id=?',
                             (revision_id, warehouse_id)).fetchone()
            result = dict(row)
            result['document'] = json.loads(result['document'])
        return result

    def publish(self, organization_id: str, warehouse_id: str, revision_id: str,
                expected_version: int) -> dict:
        # Reserve the write transaction so validation and publication see one version.
        published_id = uuid.uuid4().hex
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._owned(db, organization_id, warehouse_id)
            draft = db.execute("""SELECT document FROM layout_revisions
                WHERE id=? AND warehouse_id=? AND state='draft' AND version=?""",
                (revision_id, warehouse_id, expected_version)).fetchone()
            if draft is None:
                raise LayoutConflict('Draft changed or does not exist')
            issues = validate_geometry(json.loads(draft['document']))
            report = validate_layout(json.loads(draft['document']))
            issues = issues + [dict(i, gate='runtime') for i in report['issues'] if i['severity'] == 'error']
            if issues:
                raise LayoutInvalid(issues)
            changed = db.execute("""INSERT INTO layout_revisions(id,warehouse_id,state,document)
                SELECT ?,warehouse_id,'published',document FROM layout_revisions
                WHERE id=? AND warehouse_id=? AND state='draft' AND version=?""",
                (published_id, revision_id, warehouse_id, expected_version)).rowcount
            if changed != 1:
                raise LayoutConflict('Draft changed or does not exist')
        return self.get_revision(organization_id, warehouse_id, published_id)

    def fork_draft(self, organization_id: str, warehouse_id: str, revision_id: str) -> dict:
        """Create an independent draft from a saved revision for scenario comparison."""
        draft_id = uuid.uuid4().hex
        with self.connection() as db:
            self._owned(db, organization_id, warehouse_id)
            changed = db.execute("""INSERT INTO layout_revisions(id,warehouse_id,state,document)
                SELECT ?,warehouse_id,'draft',document FROM layout_revisions
                WHERE id=? AND warehouse_id=?""",
                (draft_id, revision_id, warehouse_id)).rowcount
            if changed != 1:
                raise LayoutNotFound('Revision not found')
        return self.get_revision(organization_id, warehouse_id, draft_id)

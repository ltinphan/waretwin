import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.layout_store import LayoutConflict, LayoutNotFound, LayoutStore
from app.layout_geometry import empty_layout


def test_tenants_cannot_read_update_or_publish_each_others_layouts(tmp_path):
    store = LayoutStore(tmp_path / 'layouts.db')
    draft = store.create('customer-a', 'Warehouse A', {'size': {'width': 100}})
    args = ('customer-b', draft['warehouse_id'], draft['id'])
    assert store.list_warehouses('customer-b') == []
    with pytest.raises(LayoutNotFound):
        store.get_revision(*args)
    with pytest.raises(LayoutNotFound):
        store.save_draft(*args, 1, {})
    with pytest.raises(LayoutNotFound):
        store.publish(*args, 1)


def test_stale_edits_and_publications_are_rejected(tmp_path):
    store = LayoutStore(tmp_path / 'layouts.db')
    draft = store.create('a', 'Warehouse', {'width': 100})
    args = ('a', draft['warehouse_id'], draft['id'])
    updated = store.save_draft(*args, 1, {'width': 60})
    assert updated['version'] == 2
    with pytest.raises(LayoutConflict):
        store.save_draft(*args, 1, {'width': 40})
    with pytest.raises(LayoutConflict):
        store.publish(*args, 1)
    assert store.get_revision(*args)['document'] == {'width': 60}


def test_published_snapshot_survives_edits_and_restart(tmp_path):
    path = tmp_path / 'layouts.db'
    store = LayoutStore(path)
    original = empty_layout('Warehouse', 100, 60, 10)
    draft = store.create('a', 'Warehouse', original)
    args = ('a', draft['warehouse_id'], draft['id'])
    published = store.publish(*args, 1)
    store.save_draft(*args, 1, {'width': 60})
    pub_args = ('a', draft['warehouse_id'], published['id'])
    assert LayoutStore(path).get_revision(*pub_args)['document'] == original
    with pytest.raises(LayoutConflict):
        store.save_draft(*pub_args, 1, {'width': 20})
    with store.connection() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('DELETE FROM layout_revisions WHERE id=?', (published['id'],))


def test_reject_non_json_numbers(tmp_path):
    store = LayoutStore(tmp_path / 'layouts.db')
    with pytest.raises(ValueError):
        store.create('a', 'Warehouse', {'width': float('nan')})
    assert store.list_warehouses('a') == []


def test_concurrent_writers_have_one_winner_and_no_lost_update(tmp_path):
    store = LayoutStore(tmp_path / 'layouts.db')
    draft = store.create('a', 'Warehouse', empty_layout('A', 20, 20, 10))
    args = ('a', draft['warehouse_id'], draft['id'])
    ready = Barrier(2)

    def save(name):
        document = empty_layout(name, 20, 20, 10)
        ready.wait(timeout=5)
        try:
            return store.save_draft(*args, 1, document)
        except LayoutConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, ['first', 'second']))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert winners[0]['version'] == 2
    assert store.get_revision(*args) == winners[0]

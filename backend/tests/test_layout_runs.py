"""Tests for tenant-scoped, revision-pinned simulation runs."""
import pytest

from app.layout_geometry import empty_layout
from app.layout_runs import ACTIVE, ENDED, IDLE_PAUSED, PAUSED, LayoutRuns, RunInvalid
from app.layout_store import LayoutNotFound, LayoutStore


def _warehouse(store, org='a', name='W'):
    return store.create(org, name, empty_layout(name, 40, 30, 8))


def _published(store, org, warehouse_id):
    draft = store.list_revisions(org, warehouse_id)[0]
    return store.publish(org, warehouse_id, draft['id'], draft['version'])


def test_runs_pin_published_revisions_and_survive_restart(tmp_path):
    path = tmp_path / 'layouts.db'
    store = LayoutStore(path)
    wh = _warehouse(store)
    org, wid = 'a', wh['warehouse_id']
    pub = _published(store, org, wid)
    # a second revision published later must not affect the run
    fork = store.fork_draft(org, wid, pub['id'])
    pub2 = store.publish(org, wid, fork['id'], fork['version'])

    runs = LayoutRuns(path)
    run = runs.create(org, wid, pub['id'], 'Baseline', {'seed': 7, 'robots': 4, 'cell': 1.0})
    assert run['status'] == ACTIVE
    assert run['settings'] == {'seed': 7, 'robots': 4, 'cell': 1.0}

    reopened = LayoutRuns(path)  # restart persistence
    fetched = reopened.get(org, run['id'])
    assert fetched['revision_id'] == pub['id']
    assert fetched['settings']['seed'] == 7
    assert pub2['id'] != pub['id']


def test_draft_revision_rejected(tmp_path):
    path = tmp_path / 'layouts.db'
    store = LayoutStore(path)
    wh = _warehouse(store)
    org, wid = 'a', wh['warehouse_id']
    draft = store.list_revisions(org, wid)[0]
    runs = LayoutRuns(path)
    with pytest.raises(RunInvalid):
        runs.create(org, wid, draft['id'], 'From draft', {})
    with pytest.raises(LayoutNotFound):
        runs.create(org, wid, 'missing-revision', 'X', {})


def test_tenant_isolation(tmp_path):
    path = tmp_path / 'layouts.db'
    store = LayoutStore(path)
    wh = _warehouse(store, org='a')
    org, wid = 'a', wh['warehouse_id']
    pub = _published(store, org, wid)
    runs = LayoutRuns(path)
    run = runs.create(org, wid, pub['id'], 'Run A', {})
    with pytest.raises(LayoutNotFound):
        runs.get('b', run['id'])
    with pytest.raises(LayoutNotFound):
        runs.list('b', wid)
    with pytest.raises(LayoutNotFound):
        runs.end('b', run['id'])


def test_idle_pause_transition_with_explicit_clock(tmp_path):
    path = tmp_path / 'layouts.db'
    store = LayoutStore(path)
    wh = _warehouse(store)
    org, wid = 'a', wh['warehouse_id']
    pub = _published(store, org, wid)
    runs = LayoutRuns(path)
    run = runs.create(org, wid, pub['id'], 'R', {}, now=1000.0)
    # heartbeat within threshold stays active
    assert runs.update_activity(org, run['id'], now=1500.0)['status'] == ACTIVE
    # past threshold -> idle_paused
    assert runs.update_activity(org, run['id'], now=1500.0 + 901.0)['status'] == IDLE_PAUSED
    # resume then explicit pause
    assert runs.resume(org, run['id'])['status'] == ACTIVE
    assert runs.pause(org, run['id'])['status'] == PAUSED
    assert runs.resume(org, run['id'])['status'] == ACTIVE
    assert runs.end(org, run['id'])['status'] == ENDED
    # ended is terminal
    with pytest.raises(RunInvalid):
        runs.resume(org, run['id'])
    with pytest.raises(RunInvalid):
        runs.pause(org, run['id'])


def test_invalid_transitions_and_settings(tmp_path):
    path = tmp_path / 'layouts.db'
    store = LayoutStore(path)
    wh = _warehouse(store)
    org, wid = 'a', wh['warehouse_id']
    pub = _published(store, org, wid)
    runs = LayoutRuns(path)
    run = runs.create(org, wid, pub['id'], 'R', {})
    runs.pause(org, run['id'])
    with pytest.raises(RunInvalid):  # paused -> idle_paused is not a legal transition
        runs._transition(org, run['id'], 'idle_paused')
    runs.end(org, run['id'])
    with pytest.raises(RunInvalid):  # ended is terminal
        runs.pause(org, run['id'])
    with pytest.raises(ValueError):
        runs.create(org, wid, pub['id'], 'Bad settings', {'seed': float('nan')})
    with pytest.raises(ValueError):
        runs.create(org, wid, pub['id'], '  ', {})

"""Wave-2 API routes: runs, templates, publish gate on runtime validation."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.layout_api import get_runs, get_store, router
from app.layout_runs import LayoutRuns
from app.layout_store import LayoutStore
from app.layout_templates import multifloor_with_lift


def _client(tmp_path):
    store = LayoutStore(tmp_path / 'layouts.db')
    runs = LayoutRuns(tmp_path / 'layouts.db')
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_runs] = lambda: runs
    client = TestClient(app)
    token = store.issue_access('org-a', 'owner')
    return client, store, {'Authorization': f'Bearer {token}'}


def test_run_crud_and_publish_gate(tmp_path):
    client, store, auth = _client(tmp_path)
    created = client.post('/api/workspace/warehouses', headers=auth, json={
        'name': 'A', 'document': multifloor_with_lift('A', 30, 30, {})})
    assert created.status_code == 201, created.text
    draft = created.json()
    wh, rev = draft['warehouse_id'], draft['id']
    # publish the valid template draft
    pub = client.post(f'/api/workspace/warehouses/{wh}/revisions/{rev}/publish',
                      headers=auth, json={'expected_version': 1})
    assert pub.status_code == 201, pub.text
    published = pub.json()
    # run on published revision works
    run = client.post(f'/api/workspace/warehouses/{wh}/revisions/{published["id"]}/runs',
                      headers=auth, json={'name': 'night shift', 'settings': {'speed': 2}})
    assert run.status_code == 201, run.text
    body = run.json()
    assert body['status'] == 'active'
    # run on draft revision is rejected
    draft_run = client.post(f'/api/workspace/warehouses/{wh}/revisions/{rev}/runs',
                            headers=auth, json={'name': 'x'})
    assert draft_run.status_code == 422
    # pause/resume/end cycle
    base = f'/api/workspace/warehouses/{wh}/runs/{body["id"]}'
    assert client.post(base + '/pause', headers=auth).json()['status'] == 'paused'
    assert client.post(base + '/resume', headers=auth).json()['status'] == 'active'
    assert client.get(f'/api/workspace/warehouses/{wh}/runs', headers=auth).json()[0]['id'] == body['id']


def test_template_apply_creates_valid_warehouse(tmp_path):
    client, store, auth = _client(tmp_path)
    response = client.post('/api/workspace/warehouses/templates:apply', headers=auth, json={
        'name': 'Tpl', 'width_m': 30, 'depth_m': 30,
        'params': {'_template': 'racking_bays', 'n_aisles': 2}})
    assert response.status_code == 201, response.text
    doc = response.json()
    assert doc['document']['size']['width'] == 30
    # unknown template -> 400
    bad = client.post('/api/workspace/warehouses/templates:apply', headers=auth, json={
        'name': 'Bad', 'width_m': 30, 'depth_m': 30, 'params': {'_template': 'nope'}})
    assert bad.status_code == 400
    # impossible dims -> 422
    bad2 = client.post('/api/workspace/warehouses/templates:apply', headers=auth, json={
        'name': 'Bad2', 'width_m': 5, 'depth_m': 5, 'params': {'_template': 'racking_bays'}})
    assert bad2.status_code == 422


def test_publish_blocked_by_runtime_validation(tmp_path):
    client, store, auth = _client(tmp_path)
    created = client.post('/api/workspace/warehouses', headers=auth, json={
        'name': 'A', 'document': multifloor_with_lift('A', 30, 30, {})})
    draft = created.json()
    wh, rev = draft['warehouse_id'], draft['id']
    # break an operational ref: point a location's access_point into a rack
    doc = client.get(f'/api/workspace/warehouses/{wh}/revisions/{rev}', headers=auth).json()['document']
    doc['locations'][0]['access_point'] = [1.0, 1.0]  # inside the first rack
    saved = client.put(f'/api/workspace/warehouses/{wh}/revisions/{rev}', headers=auth,
                       json={'expected_version': 1, 'document': doc})
    assert saved.status_code == 200
    pub = client.post(f'/api/workspace/warehouses/{wh}/revisions/{rev}/publish',
                      headers=auth, json={'expected_version': 2})
    assert pub.status_code == 422, pub.text
    issues = pub.json()['detail']['issues']
    assert any(i.get('gate') == 'runtime' for i in issues), issues

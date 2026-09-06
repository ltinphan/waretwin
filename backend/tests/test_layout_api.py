from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.layout_api import get_store, router
from app.layout_store import LayoutStore
from app.layout_geometry import empty_layout


def test_authenticated_layout_lifecycle_and_tenant_isolation(tmp_path):
    store = LayoutStore(tmp_path / 'layouts.db')
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app)
    token = store.issue_access('customer-a', 'owner')
    a = {'Authorization': f'Bearer {token}'}
    b = {'Authorization': f'Bearer {store.issue_access("customer-b", "owner-b")}'}
    path = '/api/workspace/warehouses'
    assert client.get(path).status_code == 401
    response = client.post(path, headers=a, json={'name': 'A', 'document': empty_layout('A', 100, 60, 10)})
    assert response.status_code == 201
    draft = response.json()
    revision = f'{path}/{draft["warehouse_id"]}/revisions/{draft["id"]}'
    assert client.get(path, headers=b).json() == []
    assert client.get(revision, headers=b).status_code == 404
    payload = {'expected_version': 1, 'document': empty_layout('A', 60, 60, 10)}
    assert client.put(revision, headers=b, json=payload).status_code == 404
    assert client.post(revision + '/publish', headers=b, json={'expected_version': 1}).status_code == 404
    assert client.put(revision, headers=a, json=payload).status_code == 200
    assert client.put(revision, headers=a, json=payload).status_code == 409
    published = client.post(revision + '/publish', headers=a, json={'expected_version': 2})
    assert published.status_code == 201
    pubpath = f'{path}/{draft["warehouse_id"]}/revisions/{published.json()["id"]}'
    assert client.put(pubpath, headers=a, json=payload).status_code == 409
    assert client.get(pubpath, headers=a).json()['document']['size']['width'] == 60
    assert client.post(pubpath + '/fork', headers=b).status_code == 404
    fork = client.post(pubpath + '/fork', headers=a)
    assert fork.status_code == 201
    forkpath = f'{path}/{draft["warehouse_id"]}/revisions/{fork.json()["id"]}'
    assert client.put(forkpath, headers=a, json={
        'expected_version': 1, 'document': {'width': 80},
    }).status_code == 200
    assert client.get(pubpath, headers=a).json()['document']['size']['width'] == 60
    store.revoke_access(token)
    assert client.get(revision, headers=a).status_code == 401


def test_token_storage_contains_no_raw_token_and_expiration_is_enforced(tmp_path):
    store = LayoutStore(tmp_path / 'layouts.db')
    token = store.issue_access('a', 'user')
    with store.connection() as db:
        row = db.execute('SELECT * FROM layout_access_tokens').fetchone()
        assert token not in tuple(row)
        db.execute('UPDATE layout_access_tokens SET expires_at=0')
    assert store.authenticate(token) is None


def test_dimension_workflow_preserves_equipment_and_rejects_stale_resize(tmp_path):
    store = LayoutStore(tmp_path / 'layouts.db')
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app)
    headers = {'Authorization': f'Bearer {store.issue_access("a", "owner")}'}
    created = client.post('/api/workspace/warehouses/empty', headers=headers, json={
        'name': 'Factory', 'width': 100, 'depth': 70, 'height': 10, 'cell_size': 0.5,
    })
    assert created.status_code == 201
    revision = created.json()
    document = revision['document']
    document['racks'] = [{'id': 'r1', 'position': [80, 0, 20], 'size': [5, 4, 2], 'rotation': 0}]
    path = f'/api/workspace/warehouses/{revision["warehouse_id"]}/revisions/{revision["id"]}'
    assert client.put(path, headers=headers, json={'expected_version': 1, 'document': document}).status_code == 200
    resize = {'expected_version': 2, 'width': 60, 'depth': 40, 'height': 10}
    response = client.post(path + '/resize', headers=headers, json=resize)
    assert response.status_code == 200
    assert response.json()['document']['racks'] == document['racks']
    assert response.json()['document']['grid']['cols'] == 120
    assert client.post(path + '/resize', headers=headers, json=resize).status_code == 409
    assert client.post(path + '/resize', headers=headers, json={**resize, 'width': -1}).status_code == 422
    validation = client.get(path + '/validation', headers=headers)
    assert validation.status_code == 200
    assert validation.json()['version'] == 3
    assert validation.json()['valid'] is False
    blocked = client.post(path + '/publish', headers=headers, json={'expected_version': 3})
    assert blocked.status_code == 422
    assert any(i['code'] == 'outside_floor' for i in blocked.json()['detail']['issues'])
    assert len(store.list_revisions('a', revision['warehouse_id'])) == 1
    assert client.get(path + '/validation').status_code == 401
    other = {'Authorization': f'Bearer {store.issue_access("b", "other")}'}
    assert client.get(path + '/validation', headers=other).status_code == 404

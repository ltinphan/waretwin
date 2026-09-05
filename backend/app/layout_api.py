"""Authenticated layout routes. The public demo remains independent."""
from functools import lru_cache
import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .layout_store import LayoutConflict, LayoutInvalid, LayoutNotFound, LayoutStore
from .layout_geometry import empty_layout, resize_layout, validate_geometry


router = APIRouter(prefix='/api/workspace', tags=['Customer layouts'])
bearer = HTTPBearer(auto_error=False)


@lru_cache
def get_store() -> LayoutStore:
    return LayoutStore(os.environ.get('TWIN_LAYOUT_DB', 'layouts.db'))


def identity(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
             store: Annotated[LayoutStore, Depends(get_store)]) -> dict:
    user = store.authenticate(credentials.credentials) if credentials else None
    if not user:
        raise HTTPException(401, 'Workspace authentication required', headers={'WWW-Authenticate': 'Bearer'})
    return user


Store = Annotated[LayoutStore, Depends(get_store)]
User = Annotated[dict, Depends(identity)]


class NewWarehouse(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    document: dict[str, Any]


class SaveDraft(BaseModel):
    expected_version: int = Field(ge=1)
    document: dict[str, Any]


class PublishDraft(BaseModel):
    expected_version: int = Field(ge=1)


class Dimensions(BaseModel):
    width: float = Field(gt=0, allow_inf_nan=False)
    depth: float = Field(gt=0, allow_inf_nan=False)
    height: float = Field(gt=0, allow_inf_nan=False)


class EmptyWarehouse(Dimensions):
    name: str = Field(min_length=1, max_length=160)
    cell_size: float = Field(default=1, gt=0, allow_inf_nan=False)


class ResizeDraft(Dimensions):
    expected_version: int = Field(ge=1)


def operation(fn, *args):
    try:
        return fn(*args)
    except LayoutNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except LayoutConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except LayoutInvalid as exc:
        raise HTTPException(422, {'message': str(exc), 'issues': exc.issues}) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/me')
def me(user: User):
    return user


@router.get('/warehouses')
def warehouses(user: User, store: Store):
    return store.list_warehouses(user['organization_id'])


@router.post('/warehouses/empty', status_code=201)
def create_empty(body: EmptyWarehouse, user: User, store: Store):
    document = operation(empty_layout, body.name, body.width, body.depth, body.height, body.cell_size)
    return operation(store.create, user['organization_id'], body.name, document)


@router.post('/warehouses', status_code=201)
def create(body: NewWarehouse, user: User, store: Store):
    return operation(store.create, user['organization_id'], body.name, body.document)


@router.get('/warehouses/{warehouse_id}/revisions')
def revisions(warehouse_id: str, user: User, store: Store):
    return operation(store.list_revisions, user['organization_id'], warehouse_id)


@router.get('/warehouses/{warehouse_id}/revisions/{revision_id}')
def revision(warehouse_id: str, revision_id: str, user: User, store: Store):
    return operation(store.get_revision, user['organization_id'], warehouse_id, revision_id)


@router.put('/warehouses/{warehouse_id}/revisions/{revision_id}')
def save(warehouse_id: str, revision_id: str, body: SaveDraft, user: User, store: Store):
    return operation(store.save_draft, user['organization_id'], warehouse_id, revision_id,
                     body.expected_version, body.document)


@router.post('/warehouses/{warehouse_id}/revisions/{revision_id}/publish', status_code=201)
def publish(warehouse_id: str, revision_id: str, body: PublishDraft, user: User, store: Store):
    return operation(store.publish, user['organization_id'], warehouse_id, revision_id,
                     body.expected_version)


@router.get('/warehouses/{warehouse_id}/revisions/{revision_id}/validation')
def validation(warehouse_id: str, revision_id: str, user: User, store: Store):
    current = operation(store.get_revision, user['organization_id'], warehouse_id, revision_id)
    issues = validate_geometry(current['document'])
    return {'version': current['version'], 'valid': not issues, 'issues': issues}


@router.post('/warehouses/{warehouse_id}/revisions/{revision_id}/fork', status_code=201)
def fork(warehouse_id: str, revision_id: str, user: User, store: Store):
    return operation(store.fork_draft, user['organization_id'], warehouse_id, revision_id)


@router.post('/warehouses/{warehouse_id}/revisions/{revision_id}/resize')
def resize(warehouse_id: str, revision_id: str, body: ResizeDraft, user: User, store: Store):
    current = operation(store.get_revision, user['organization_id'], warehouse_id, revision_id)
    if current['version'] != body.expected_version or current['state'] != 'draft':
        raise HTTPException(409, 'Draft changed or is published')
    try:
        document = resize_layout(current['document'], body.width, body.depth, body.height)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, 'Layout dimensions or grid are invalid') from exc
    return operation(store.save_draft, user['organization_id'], warehouse_id, revision_id,
                     body.expected_version, document)

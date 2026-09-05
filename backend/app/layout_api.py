"""Authenticated layout routes. The public demo remains independent."""
from functools import lru_cache
import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .layout_store import LayoutConflict, LayoutInvalid, LayoutNotFound, LayoutStore
from .layout_geometry import empty_layout, resize_layout, validate_geometry
from .layout_runs import ACTIVE, LayoutRuns, RunInvalid
from .layout_templates import (conveyor_loop, multifloor_with_lift, racking_bays,
                               assert_template_valid)
from .layout_validation import validate_layout
from .layout_import import import_dxf, import_pdf_plan, calibrate_image


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


@lru_cache
def get_runs() -> LayoutRuns:
    """Runs live in the same SQLite file as the layout store (TWIN_LAYOUT_DB)."""
    return LayoutRuns(os.environ.get('TWIN_LAYOUT_DB', 'layouts.db'))


Runs = Annotated[LayoutRuns, Depends(get_runs)]


class NewRun(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    settings: dict[str, Any] = Field(default_factory=dict)


class TemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    width_m: float = Field(gt=0, allow_inf_nan=False)
    depth_m: float = Field(gt=0, allow_inf_nan=False)
    params: dict[str, Any] = Field(default_factory=dict)


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


# ── Simulation runs (wave-2): tenant-scoped, pinned to published revisions ──

@router.post('/warehouses/{warehouse_id}/revisions/{revision_id}/runs', status_code=201)
def create_run(warehouse_id: str, revision_id: str, body: NewRun, user: User, runs: Runs):
    return operation(runs.create, user['organization_id'], warehouse_id, revision_id,
                     body.name, body.settings)


@router.get('/warehouses/{warehouse_id}/runs')
def list_runs(warehouse_id: str, user: User, runs: Runs):
    return operation(runs.list, user['organization_id'], warehouse_id)


@router.get('/warehouses/{warehouse_id}/runs/{run_id}')
def get_run(warehouse_id: str, run_id: str, user: User, runs: Runs):
    return operation(runs.get, user['organization_id'], run_id)


@router.post('/warehouses/{warehouse_id}/runs/{run_id}/pause')
def pause_run(warehouse_id: str, run_id: str, user: User, runs: Runs):
    return operation(runs.pause, user['organization_id'], run_id)


@router.post('/warehouses/{warehouse_id}/runs/{run_id}/resume')
def resume_run(warehouse_id: str, run_id: str, user: User, runs: Runs):
    return operation(runs.resume, user['organization_id'], run_id)


@router.post('/warehouses/templates:apply', status_code=201)
def apply_template(body: TemplateRequest, user: User, store: Store):
    """Generate a layout from a parameterized template and save it as a new draft."""
    builders = {'racking_bays': racking_bays, 'multifloor_with_lift': multifloor_with_lift,
                'conveyor_loop': conveyor_loop}
    builder = builders.get(body.params.pop('_template', None))
    if builder is None:
        raise HTTPException(400, "params._template must be one of " + ", ".join(sorted(builders)))
    try:
        layout = builder(body.name, body.width_m, body.depth_m, body.params)
        assert_template_valid(layout)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    # A template is its own warehouse (the path's warehouse is untouched).
    return operation(store.create, user['organization_id'], body.name, layout)


# ── Imports (wave-2): parse to a document; the client saves it as a draft ──

@router.post('/warehouses/{warehouse_id}/revisions/{revision_id}/imports:dxf')
def import_dxf_route(warehouse_id: str, revision_id: str, user: User, store: Store,
                     units: str, file: 'UploadFile'):
    """DXF → layout document (mandatory unit confirmation; header mismatch warns)."""
    try:
        return import_dxf(file.file.read(), units=units)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/warehouses/{warehouse_id}/revisions/{revision_id}/imports:pdf')
def import_pdf_route(warehouse_id: str, revision_id: str, user: User, store: Store,
                     scale_m_per_unit: float, file: 'UploadFile'):
    """PDF vector plan → layout document at the confirmed scale."""
    try:
        return import_pdf_plan(file.file.read(), scale_m_per_unit=scale_m_per_unit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/warehouses/{warehouse_id}/imports:image:calibrate')
def import_image_calibrate(user: User, known_length_px: float, known_length_m: float,
                           file: 'UploadFile'):
    """Return m/px for a floor-plan image; used before PDF/raster import."""
    try:
        return calibrate_image(file.file.read(), known_length_px=known_length_px,
                               known_length_m=known_length_m)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

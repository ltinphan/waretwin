# Customer layout implementation

Goal: customers configure their own warehouses without code changes or Docker rebuilds.

## Acceptance criteria

- [ ] Server-authenticated organization membership and warehouse access.
- [ ] Persistent warehouses, drafts, immutable published revisions and run references.
- [ ] Concurrent draft edits reject stale versions.
- [ ] Runtime layout loading shared by the 2D editor, 3D view and simulation.
- [ ] Dimensions, units, irregular floor boundaries and multiple floors.
- [ ] Equipment placement, rotation, snapping, duplication and undo/redo.
- [ ] Expansion preserves equipment; shrinking flags out-of-bounds objects.
- [ ] Templates generate arrangements with physical equipment/aisle dimensions.
- [ ] Geometry, connectivity, starting-position and clearance validation.
- [ ] Separate per-customer simulation runs, paused when idle.
- [ ] Python/TypeScript navigation parity including rotation and cell sizes.
- [ ] Calibrated image/PDF backgrounds and DXF import with unit confirmation.
- [ ] Editable previews for arrangement generation and AI-assisted recognition.
- [ ] Compare layout alternatives using reproducible simulation settings.
- [ ] Desktop/mobile visual verification, two-customer isolation and regression tests.
- [ ] Verified deployment with persistent data and rollback instructions.

## Architecture

Organization -> warehouse -> revision -> simulation run. Authentication supplies
the organization identity; an ID supplied by a client is never sufficient proof
of access. Drafts use optimistic concurrency. Publishing creates an immutable
snapshot. Runs reference a published revision and must never follow later edits.

Store physical coordinates in metres. Derive navigation grids from geometry;
changing grid resolution must not change building or equipment dimensions.
Building geometry, equipment specifications and operating assumptions remain
separate. Use the existing demo as a template and preserve its public behavior.

## Progress

Implementation branch: `codex/customer-layouts`. Production is unchanged.
Implemented components: SQLite revision persistence with explicit tenant
predicates, immutable publication, optimistic concurrency and independent forks.
Authenticated `/api/workspace` routes derive ownership from expiring, revocable
tokens stored as SHA-256 digests. Token provisioning is administrative only;
customer sign-in and membership management still need a product flow.
The frontend has a typed workspace API client that holds tokens in memory.

Focused persistence and HTTP tests cover cross-tenant read/edit/publication/fork,
stale edits, immutable publication, restart persistence, token expiry and revocation.
Publication now checks geometry inside the same SQLite write transaction that
copies the requested draft version, rejecting invalid geometry with structured
HTTP 422 issues. Authenticated validation reports are available to the editor.
This is not yet the complete simulation-readiness gate: connectivity, clearance,
operational references and full runtime schema validation remain unfinished.

Dimension operations now create empty warehouses and resize drafts through
authenticated routes. Resizing preserves every equipment object and derives
grid rows/columns from physical dimensions. Shapely-based geometry checks cover
concave floor boundaries, rotated rack extents and rectangle bounds; they are
not yet a complete schema/connectivity/clearance validator. The geometry gate
also checks malformed collections, object IDs, point positions, conveyor width,
lift cells at non-1m resolution, column bases and upper-floor rack elevations.
Twenty-eight focused tests pass for persistence, API isolation and geometry,
including concurrent draft writers. Draft save responses retain the exact
version written within their transaction rather than rereading after commit.
Local geometry tests use Python 3.14 with NumPy 2.5.2; the deployment lock remains
Python 3.11 with NumPy 2.2.6 and needs verification in that environment.

The `/workspace` editor builds successfully and supports rack manipulation,
undo/redo, draft saves, alternatives and saved-geometry reports. It is still
local-only and requires desktop/mobile visual verification. The frontend's
existing 32 tests pass; they do not yet cover the new editor interactions.

Navigation rasterization now uses polygon geometry (Shapely on Python,
polygon-clipping on TypeScript) for concave boundaries, rotated racks, diagonal
conveyors and walkway areas. Missing floors and partial boundary cells remain
blocked. Lift cell coordinates are converted to physical metres, and shafts
are blocked only on served floors. A cross-language test compares complete
cell masks, including the existing demo, at multiple grid resolutions. CI now
installs the Python dependencies in the frontend job to run this comparison.
The simulation engine's movement/lift state machines still contain 1m-cell
assumptions; matching rasterization is not yet end-to-end non-1m simulation.

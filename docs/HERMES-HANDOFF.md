# WareTwin customer-layout implementation handoff

The user explicitly requested that Hermes (the agent behind their Discord bot)
take over this implementation from Codex. Continue the full customer layout
project, not just CI/CD setup. Send an acknowledgement and progress/results to
the configured Discord home channel using send_message. Do not expose secrets.

## Working copy

- VPS worktree: `/root/.hermes/shared/waretwin-customer-layouts-handoff`
- Branch: `codex/customer-layouts-handoff-20260905`
- Base commit: `da79c98b0ec050aec5846cb5c3633a19696922b4`
- All local uncommitted implementation files have been transferred here.
- Production checkout is a DIFFERENT directory: `/root/.hermes/shared/waretwin`.
- Do not overwrite production or deploy until the full scope is tested.
- Hermes gateway and terminal now run on the host as root. Docker still hosts
  applications. `/output` links to `/root/.hermes/shared`.
- No model change or safety/approval bypass is authorized by this handoff.

## Objective and acceptance

Implement the entire accepted scope in `docs/CUSTOMER-LAYOUTS.md`. Customers must
configure warehouses without code changes or rebuilds. Scope includes tenant
auth/membership, persistent drafts and immutable published revisions, shared
runtime layout for 2D/3D/simulation, physical dimensions and arbitrary floors,
equipment editing, templates, geometry/connectivity/clearance validation,
isolated idle-pausing runs, reproducible alternative comparison, calibrated
image/PDF and DXF imports, editable generated/AI recognition previews, responsive
visual verification and tested deployment/rollback. Do not mark complete for
the partial foundations already implemented.

## Implemented locally

- `backend/app/layout_store.py`: SQLite org-scoped token auth, warehouses,
  optimistic draft writes, transactional geometry-checked publication, immutable
  snapshots and alternative forks. Expiring tokens store only SHA256 digests.
- `backend/app/layout_api.py`: authenticated `/api/workspace` routes, empty
  warehouse creation, resizing, validation, save/publish/fork.
- `backend/app/layout_geometry.py`: Shapely physical validation. Drafts may be
  saved invalid; publication rejects geometry errors. NOT a complete runtime
  schema, connectivity, clearance or operational-reference validator yet.
- `frontend/src/workspace/Workspace.tsx`: `/workspace` token sign-in, warehouse
  dimensions, rack plan/drag/rotation/duplicate/delete/undo/redo, save/fork/export,
  saved-geometry reports. No production rollout or visual verification yet.
- Python/TS navgrid builders now handle concave boundaries, rotated racks,
  polygon walkways, square-ended diagonal conveyors, physical lift cell positions
  and served floors. Shared mask comparison test in `frontend/tests/navgrid.test.ts`.
- Most recent edits route engine world/grid conversions through layout-aware
  helpers in both languages: movement, occupancy, perception, service points,
  spawn positions/elevations, lift coordinates and congestion bounds.
- `test_grid_resolution.py` and `grid-resolution.test.ts`: six tests each for
  physical movement, service lookup, lift spacing and congestion at 0.5/1/2m.
  Engine arrival tolerance is 0.08m; tests preserve that existing behavior.

## Verification at handoff

- Latest frontend complete suite: 44 tests passed; latest production build passed.
- Latest focused resolution tests: Python 6 passed; TypeScript 6 passed.
- Previous backend full suite before newest conversion edits: 83 passed.
- Latest full backend suite was running on the LOCAL Codex machine at packaging;
  the Discord handoff notice may provide its completed result. Re-run after edits.
- Python venv/node_modules are NOT included in the archive. Use Python 3.11 and
  `backend/requirements.lock`; add pytest/httpx per `.github/workflows/ci.yml`.
- Run `npm ci`, `npm test`, `npm run build` in frontend. Frontend parity tests
  also require Python/Shapely; set PYTHON to the backend venv executable.
- Run backend pytest using a scratch TWIN_DB/TWIN_LAYOUT_DB, never production DBs.
- Existing frontend build warns about bundle size. Do not blindly force-upgrade
  dependencies to fix unrelated npm audit warnings.

## Known unfinished work and next steps

1. Inspect current diff, re-run focused/full tests, then finish non-1m safety:
   physical robot clearance, multi-robot routes, cross-floor full trips and path
   sampling. Matching masks and one-robot movement are NOT sufficient proof.
2. Lift state machines still hardcode floor 1/2 (queues/doors/directions). Runtime
   schema and UI must be generalized for real multifloor customer layouts.
3. Empty/custom layouts can still crash the demo task generator when shelves,
   packing/inbound/outbound locations are missing. It calls pick(empty-array).
   Guard missing operational categories without changing the demo RNG behavior.
4. The public demo still imports a singleton JSON layout. Integrate dynamic
   layouts into 2D/3D/simulation and create separate tenant-scoped runs referencing
   published revision IDs, with idle pausing and persistent run metadata.
5. Current editor mainly edits racks. Finish the full equipment/floor/import/
   template/alternative workflow and actual user membership/sign-in management.
6. Verify desktop/mobile using browser screenshots and interactions; verify 3D
   canvas pixels and movement. No screenshots have yet proven this new editor.
7. Deploy only once the full agreed acceptance checklist is proven. Preserve
   production volumes and user changes; document rollback. No volume pruning.

The current WareTwin CI/CD bridge lives at `/output/waretwin-control/client.py`.
`status` and `ci` are read-only. Its deploy action requires a clean main checkout
with a successful push CI run. At last check main had no recorded push CI, so it
correctly refused deployment. This worktree is NOT the bridge's deployment target.
Never bypass this by invoking the legacy webhook, which predates the checked
bridge. Stage/review/commit only the handed-off changes, then arrange a reviewed
merge/CI/deployment through the user's authorized workflow.

Work autonomously within this isolated worktree. If approval or user input is
needed, ask via Discord, report the exact blocker, and preserve the work.

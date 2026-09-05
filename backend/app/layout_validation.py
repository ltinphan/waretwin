"""Runtime layout validation: operational references, connectivity, clearance.

Pure functions over layout documents (metres). Complements layout_geometry.py,
which handles schema/shape checks; this module proves the layout is runnable.
"""
from __future__ import annotations

import math

from shapely.geometry import Point, box

from app.layout_geometry import COLLECTIONS, empty_layout
from app.sim.navgrid import build_nav_grid


OPERATIONAL_KINDS = ('SHELF', 'PACKING', 'SORTING', 'INBOUND', 'OUTBOUND')
# Task generator can run with any subset; these are warnings, not errors.
_WARNING_KINDS = ('SHELF', 'PACKING', 'INBOUND', 'OUTBOUND')


def validate_layout(document: dict, *, robot_clearance_m: float = 0.35,
                     resolutions: tuple = (0.5, 1.0)) -> dict:
    """Return {ok, issues:[{code,message,floor,object_id,severity}]}.

    errors block publish; warnings are advisory. Deterministic; no DB access.
    """
    issues: list[dict] = []

    def add(code, message, severity, *, floor=None, object_id=None):
        item = {'code': code, 'message': message, 'severity': severity}
        if floor is not None:
            item['floor'] = floor
        if object_id is not None:
            item['object_id'] = object_id
        issues.append(item)

    if not isinstance(document, dict):
        return {'ok': False, 'issues': [
            {'code': 'document', 'message': 'Layout must be an object', 'severity': 'error'}]}

    size = document.get('size') or {}
    width, depth = (size.get('width', 0) or 0), (size.get('depth', 0) or 0)
    if not isinstance(width, (int, float)) or width <= 0 or not isinstance(depth, (int, float)) or depth <= 0:
        return {'ok': False, 'issues': issues + [
            {'code': 'document', 'message': 'Layout size missing or non-positive', 'severity': 'error'}]}

    floors = {f['id']: f for f in document.get('floors', []) if isinstance(f, dict) and 'id' in f}
    if not floors:
        add('no_floors', 'Layout has no floors', 'error')
        return {'ok': False, 'issues': issues}

    locations = document.get('locations', []) or []

    # -- operational references --------------------------------------------
    present_kinds = {l.get('kind') for l in locations if isinstance(l, dict)}
    for kind in _WARNING_KINDS:
        if kind not in present_kinds:
            add('op_missing', f'No {kind} locations: simulation tasks of this kind are disabled',
                'warning', object_id=None)

    chargers = document.get('charging_stations', []) or []
    robots = (document.get('spawn', {}) or {}).get('robots', []) or []
    if robots and not chargers:
        add('op_missing', 'Robots are spawned but no charging station exists', 'error')

    # -- per-floor connectivity + clearance -------------------------------
    lift_by_floor: dict[int, list] = {}
    for lift in document.get('lifts', []) or []:
        for fid in lift.get('floors', []) or []:
            lift_by_floor.setdefault(fid, []).append(lift)

    for fid, floor in floors.items():
        try:
            grid = build_nav_grid(document, fid)
        except Exception as exc:  # geometry gate owns detailed schema errors
            add('navgrid_failed', f'Floor {fid}: rasterization failed: {exc}', 'error', floor=fid)
            continue

        walk = [(c, r) for r in range(grid.rows) for c in range(grid.cols) if grid.cells[r * grid.cols + c] == 0]
        if not walk:
            add('unreachable_region', f'Floor {fid} has no walkable cells', 'error', floor=fid)
            continue

        # flood-fill from the largest walkable component (union-find is overkill:
        # ponytail: O(cells) BFS, fine for <=1M cells)
        seen = set()
        best: tuple[int, tuple[int, int] | None] = (0, None)
        for cell in walk:
            if cell in seen:
                continue
            comp, frontier = 0, [cell]
            seen.add(cell)
            seed = cell
            while frontier:
                c, r = frontier.pop()
                comp += 1
                for nc, nr in ((c+1, r), (c-1, r), (c, r+1), (c, r-1)):
                    if 0 <= nc < grid.cols and 0 <= nr < grid.rows and \
                            grid.cells[nr * grid.cols + nc] == 0 and (nc, nr) not in seen:
                        seen.add((nc, nr))
                        frontier.append((nc, nr))
            if comp > best[0]:
                best = (comp, seed)

        # regions disconnected from the main component
        # label every walkable cell with its component seed
        region_of = {}
        seen2 = set()
        for cell in walk:
            if cell in seen2:
                continue
            frontier = [cell]
            seen2.add(cell)
            region_of[cell] = cell  # representative = seed
            while frontier:
                c, r = frontier.pop()
                for nc, nr in ((c+1, r), (c-1, r), (c, r+1), (c, r-1)):
                    if 0 <= nc < grid.cols and 0 <= nr < grid.rows and \
                            grid.cells[nr * grid.cols + nc] == 0 and (nc, nr) not in seen2:
                        seen2.add((nc, nr))
                        frontier.append((nc, nr))
                        region_of[(nc, nr)] = cell
        main_seed = best[1]
        stray = {cell for cell, rep in region_of.items() if rep != region_of.get(main_seed)}
        if stray:
            c0, r0 = min(stray)
            add('unreachable_region',
                f'Floor {fid}: {len(stray)} walkable cells unreachable from the main region '
                f'(near {c0 * grid.cell_size:.1f}m, {r0 * grid.cell_size:.1f}m)', 'error', floor=fid)

        # operational points and lift landing cells must join the main region
        def in_main(x: float, z: float) -> bool:
            cc, rr = int(x / grid.cell_size), int(z / grid.cell_size)
            cc = max(0, min(grid.cols - 1, cc))
            rr = max(0, min(grid.rows - 1, rr))
            if grid.cells[rr * grid.cols + cc] != 0:
                return False
            return region_of.get((cc, rr)) == region_of.get(main_seed)

        for loc in locations:
            if not isinstance(loc, dict) or loc.get('floor', 1) != fid:
                continue
            ap = loc.get('access_point')
            if vector_ok(ap) and not in_main(ap[0], ap[1]):
                add('isolated_point', f'Operational location {loc.get("id")} has an unreachable access point',
                    'error', floor=fid, object_id=loc.get('id'))
        for st in document.get('charging_stations', []) or []:
            if not isinstance(st, dict) or st.get('floor', 1) != fid:
                continue
            ap = st.get('access_point') or st.get('position')
            if vector_ok(ap) and not in_main(ap[0], ap[1]):
                add('isolated_point', f'Charging station {st.get("id")} is unreachable',
                    'error', floor=fid, object_id=st.get('id'))
        for lift in lift_by_floor.get(fid, []):
            lc = lift.get('cell')
            if not (isinstance(lc, list) and len(lc) == 2 and all(isinstance(v, int) for v in lc)):
                continue
            # robots board from a cell adjacent to the shaft rect, not inside it
            cs = grid.cell_size
            mx, mz = (lc[0] + 0.5) * cs, (lc[1] + 0.5) * cs
            c0 = max(0, int((mx - 1.4) / cs)); c1 = min(grid.cols - 1, int((mx + 1.4) / cs))
            r0 = max(0, int((mz - 1.9) / cs)); r1 = min(grid.rows - 1, int((mz + 1.9) / cs))
            ring = ([(c0 - 1, r) for r in range(r0 - 1, r1 + 2)] + [(c1 + 1, r) for r in range(r0 - 1, r1 + 2)] +
                    [(c, r0 - 1) for c in range(c0, c1 + 1)] + [(c, r1 + 1) for c in range(c0, c1 + 1)])
            boardable = any(
                0 <= c < grid.cols and 0 <= r < grid.rows and
                grid.cells[r * grid.cols + c] == 0 and
                region_of.get((c, r)) == region_of.get(main_seed)
                for c, r in ring
            )
            if not boardable:
                add('isolated_point', f'Lift {lift.get("id")} landing on floor {fid} is unreachable',
                    'error', floor=fid, object_id=lift.get('id'))

        # -- clearance: erode walkable mask by robot half-extent ----------
        for res in resolutions:
            if res <= 0 or not isinstance(res, (int, float)):
                continue
            if abs(res - grid.cell_size) < 1e-9:
                grid_res = grid
            else:
                scaled = dict(document)
                scaled['grid'] = {**document['grid'], 'cell_size': res}
                try:
                    grid_res = build_nav_grid(scaled, fid)
                except Exception:
                    continue
            erode_cells = max(1, int(math.ceil(robot_clearance_m / grid_res.cell_size)) - 1)
            cs = grid_res.cell_size
            for c, r in _operational_cells(document, fid, grid_res):
                ok_here = any(
                    0 <= c2 - e <= c + e < grid_res.cols and 0 <= r2 - e <= r + e < grid_res.rows and \
                    all(grid_res.cells[(r + dr) * grid_res.cols + (c + dc)] == 0
                        for dr in range(-e, e + 1) for dc in range(-e, e + 1))
                    for e in range(erode_cells, 0, -1)  # ponytail: relaxed erosion: try full then shrink
                    for c2, r2 in [(c, r)]
                )
                if not ok_here:
                    x, z = (c + 0.5) * cs, (r + 0.5) * cs
                    add('clearance_insufficient',
                        f'Operational point at ({x:.1f}m, {z:.1f}m) has <{robot_clearance_m}m clearance at {cs}m grid',
                        'error', floor=fid)
                break  # one representative point per floor is enough for the report

    return {'ok': not any(i['severity'] == 'error' for i in issues), 'issues': issues}


def vector_ok(value) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 2 and
            all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value))


def _operational_cells(document, fid, grid):
    """Representative operational cells (locations + chargers) on a floor."""
    seen = []
    for loc in document.get('locations', []) or []:
        if isinstance(loc, dict) and loc.get('floor', 1) == fid and vector_ok(loc.get('access_point')):
            c = min(grid.cols - 1, max(0, int(loc['access_point'][0] / grid.cell_size)))
            r = min(grid.rows - 1, max(0, int(loc['access_point'][1] / grid.cell_size)))
            seen.append((c, r))
    for st in document.get('charging_stations', []) or []:
        if isinstance(st, dict) and st.get('floor', 1) == fid:
            ap = st.get('access_point') or st.get('position')
            if vector_ok(ap):
                c = min(grid.cols - 1, max(0, int(ap[0] / grid.cell_size)))
                r = min(grid.rows - 1, max(0, int(ap[1] / grid.cell_size)))
                seen.append((c, r))
    return seen

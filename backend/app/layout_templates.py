"""Parameterized layout templates with physical equipment/aisle dimensions (C8)."""
from __future__ import annotations

import uuid

from app.layout_geometry import empty_layout, validate_geometry
from app.layout_validation import validate_layout


def _check(ok: bool, message: str):
    if not ok:
        raise ValueError(message)


def _rack(rid: str, zone: str, x: float, z: float, w: float, d: float, *,
          levels: int = 4, rotation: float = 0.0, floor: int = 1, height: float = 6.0,
          elevation: float = 0.0) -> dict:
    return {'id': rid, 'zone': zone, 'position': [x, elevation, z], 'size': [w, height, d],
            'rotation': rotation, 'levels': levels, 'model': 'rack_double',
            'blocks_grid': True, 'floor': floor}


def _loc(i: int, kind: str, x: float, z: float, floor: int = 1, rack_id: str = '') -> dict:
    return {'id': f'{kind}-{i:03d}', 'kind': kind, 'zone': 'A', 'floor': floor,
            'level_range': [1, 4], 'access_point': [x, z], 'rack_id': rack_id}


def _charger(i: int, x: float, z: float) -> dict:
    # station rect is ~0.9m; access point offset out of the blocked footprint
    return {'id': f'CHG-{i:02d}', 'zone': 'C', 'position': [x, 0.0, z], 'heading': 0.0,
            'power_kw': 3.0, 'access_point': [x, z + 0.8]}


def _stations(layout: dict, w: float, d: float):
    layout['stations'] = [
        {'id': 'PACK-01', 'kind': 'PACKING', 'zone': 'D', 'rect': [w - 8, d - 5, w - 1, d - 1],
         'access_point': [w - 4.5, d - 6]},
    ]
    layout['locations'] += [
        _loc(1, 'PACKING', w - 4.5, d - 6),
        _loc(2, 'INBOUND', 1.5, d - 1.5),
        _loc(3, 'OUTBOUND', w - 1.5, d - 6.5),
    ]


def racking_bays(name: str, width_m: float, depth_m: float, params: dict) -> dict:
    n_aisles = params.get('n_aisles', 2)
    bays = params.get('bays_per_aisle', 4)
    aisle_w = params.get('aisle_width_m', 2.0)
    rack_w = params.get('rack_width_m', 3.0)
    rack_d = params.get('rack_depth_m', 1.2)
    cell = params.get('cell_size', 1.0)
    _check(n_aisles >= 1 and bays >= 1, 'n_aisles and bays_per_aisle must be >= 1')
    _check(aisle_w > 0 and rack_w > 0 and rack_d > 0, 'dimensions must be positive')
    # racks run along x; aisles are the z-gaps between rack rows
    span_x = bays * rack_w
    span_z = n_aisles * rack_d + (n_aisles + 1) * aisle_w
    _check(span_x + 6 <= width_m, f'racking needs {span_x + 6:.1f}m width, building is {width_m}m')
    _check(span_z + 8 <= depth_m, f'racking needs {span_z + 8:.1f}m depth, building is {depth_m}m')

    layout = empty_layout(name, width_m, depth_m, 6.0, cell)
    z = aisle_w
    loc_i = 10
    for a in range(n_aisles):
        az = z + rack_d
        for b in range(bays):
            x = (width_m - span_x) / 2 + b * rack_w
            rid = f'RACK-{a+1}{b+1:02d}'
            layout['racks'].append(_rack(rid, 'A', x, z, rack_w, rack_d))
            layout['locations'].append(_loc(loc_i, 'SHELF', x + rack_w / 2,
                                            az + aisle_w / 2, rack_id=rid))
            loc_i += 1
        z = az + aisle_w
    layout['charging_stations'] = [_charger(1, 2.0, 1.5)]
    layout['spawn']['robots'] = [
        {'id': 'R01', 'position': [width_m / 2, 0, depth_m / 2], 'heading': 0.0, 'battery': 80, 'floor': 1},
        {'id': 'R02', 'position': [width_m / 2 + 1, 0, depth_m / 2], 'heading': 0.0, 'battery': 70, 'floor': 1},
    ]
    _stations(layout, width_m, depth_m)
    return layout


def multifloor_with_lift(name: str, width_m: float, depth_m: float, params: dict) -> dict:
    elevations = params.get('floors', [0, 6])
    lift_cell = params.get('lift_cell', [6, 6])  # default inside the 4m upper-floor inset
    n_aisles = params.get('n_aisles', 1)
    bays = params.get('bays_per_aisle', 3)
    aisle_w = params.get('aisle_width_m', 2.0)
    rack_w = params.get('rack_width_m', 3.0)
    rack_d = params.get('rack_depth_m', 1.2)
    cell = params.get('cell_size', 1.0)
    _check(len(elevations) >= 2, 'multifloor needs at least 2 elevations')
    _check(len(lift_cell) == 2, 'lift_cell must be [c, r]')

    layout = empty_layout(name, width_m, depth_m, max(elevations) + 6, cell)
    inset = 4.0
    layout['floors'] = [
        {'id': i + 1, 'name': f'Floor {i + 1}', 'elevation': e} for i, e in enumerate(elevations)
    ] + []
    # upper floors: inset footprint
    for f in layout['floors'][1:]:
        f['footprint'] = [[inset, inset], [width_m - inset, inset],
                          [width_m - inset, depth_m - inset], [inset, depth_m - inset]]
    layout['lifts'] = [{'id': 'LIFT-1', 'cell': lift_cell,
                        'floors': list(range(1, len(elevations) + 1)), 'ride_ticks': 60}]

    # shaft in metres
    cs = cell
    mx, mz = (lift_cell[0] + 0.5) * cs, (lift_cell[1] + 0.5) * cs
    shaft = (mx - 1.4, mz - 1.9, mx + 1.4, mz + 1.9)
    clearance = 2.0

    loc_i = 10
    for fi, floor in enumerate(layout['floors'], start=1):
        z = inset + aisle_w
        for a in range(n_aisles):
            az = z + rack_d
            for b in range(bays):
                x = inset + 2 + b * rack_w
                if _intersects(x - clearance, z - clearance, x + rack_w + clearance,
                               az + rack_d + clearance, shaft):
                    continue  # keep racks clear of the shaft
                rid = f'RACK-F{fi}-{a+1}{b+1:02d}'
                layout['racks'].append(_rack(rid, 'A', x, z, rack_w, rack_d, floor=fi,
                                              height=4.5, elevation=float(elevations[fi - 1])))
                layout['locations'].append(_loc(loc_i, 'SHELF', x + rack_w / 2,
                                                az + aisle_w / 2, floor=fi, rack_id=rid))
                loc_i += 1
            z = az + aisle_w
    layout['charging_stations'] = [_charger(1, 2.0, 1.5)]
    layout['spawn']['robots'] = [
        {'id': 'R01', 'position': [width_m / 2, 0, depth_m / 2], 'heading': 0.0, 'battery': 80, 'floor': 1}]
    _stations(layout, width_m, depth_m)
    return layout


def _intersects(ax0, az0, ax1, az1, other) -> bool:
    ox0, oz0, ox1, oz1 = other
    return not (ax1 < ox0 or ax0 > ox1 or az1 < oz0 or az0 > oz1)


def conveyor_loop(name: str, width_m: float, depth_m: float, params: dict) -> dict:
    loop_w = params.get('loop_w_m', 20)
    loop_d = params.get('loop_d_m', 10)
    band_w = params.get('conveyor_width_m', 0.8)
    rack_w = params.get('rack_width_m', 3.0)
    rack_d = params.get('rack_depth_m', 1.2)
    aisle_w = params.get('aisle_width_m', 2.0)
    bays = params.get('bays_per_aisle', 3)
    cell = params.get('cell_size', 1.0)
    _check(loop_w > 2 and loop_d > 2, 'loop dimensions must exceed 2m')
    _check(band_w > 0, 'conveyor width must be positive')
    cx, cz = params.get('corner', [(width_m - loop_w) / 2, (depth_m - loop_d) / 2])
    x0, z0 = cx, cz
    x1, z1 = cx + loop_w, cz + loop_d
    _check(0 <= x0 and x1 <= width_m and 0 <= z0 and z1 <= depth_m,
           f'loop {loop_w}x{loop_d}m does not fit inside {width_m}x{depth_m}m building')

    layout = empty_layout(name, width_m, depth_m, 6.0, cell)
    gap = 3.0  # ponytail: open segment keeps the ring interior reachable; full rings block robots
    layout['conveyors'] = [{'id': 'CONV-1', 'floor': 1, 'width': band_w,
                            'path': [[x0 + gap, z0], [x1, z0], [x1, z1],
                                     [x0, z1], [x0, z0 + gap]]}]
    # racks inside the ring, clear of the conveyor band
    inner_x0, inner_z0 = x0 + band_w + aisle_w, z0 + band_w + aisle_w
    loc_i = 10
    z = inner_z0
    for b in range(bays):
        x = inner_x0 + b * (rack_w + aisle_w)
        if x + rack_w > x1 - band_w - aisle_w:
            break
        rid = f'RACK-I{b+1:02d}'
        layout['racks'].append(_rack(rid, 'B', x, z, rack_w, rack_d))
        layout['locations'].append(_loc(loc_i, 'SHELF', x + rack_w / 2,
                                        z - aisle_w / 2, rack_id=rid))
        loc_i += 1
    layout['charging_stations'] = [_charger(1, width_m / 2, depth_m - 1.5)]
    layout['spawn']['robots'] = [
        {'id': 'R01', 'position': [width_m / 2, 0, 1.5], 'heading': 0.0, 'battery': 80, 'floor': 1}]
    _stations(layout, width_m, depth_m)
    return layout


TEMPLATE_VALIDATORS = (validate_geometry,)


def assert_template_valid(layout: dict) -> None:
    """Raise if a template output fails the geometry or runtime validation gates."""
    issues = validate_geometry(layout)
    _check(not issues, f'template failed geometry validation: {issues}')
    report = validate_layout(layout)
    errors = [i for i in report['issues'] if i['severity'] == 'error']
    _check(not errors, f'template failed runtime validation: {errors}')

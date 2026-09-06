"""Tests for layout templates (C8): validity, dimension round-trips, multifloor clearance."""
import pytest

from app.layout_geometry import validate_geometry
from app.layout_templates import (assert_template_valid, conveyor_loop,
                                  multifloor_with_lift, racking_bays)
from app.layout_validation import validate_layout


def test_racking_bays_valid_and_aisle_roundtrip():
    lay = racking_bays('Rack warehouse', 30, 20, {'n_aisles': 2, 'bays_per_aisle': 4,
                                                   'aisle_width_m': 2.0})
    assert validate_geometry(lay) == []
    rep = validate_layout(lay)
    assert rep['ok'] is True, rep['issues']
    assert len(lay['racks']) == 8
    # aisle width round-trip: gap between rack footprint edges == aisle param
    r1 = lay['racks'][0]['position'][2] + lay['racks'][0]['size'][2]  # end of row 1
    r2 = lay['racks'][4]['position'][2]  # start of row 2
    assert r2 - r1 == 2.0
    # racks same size as params
    assert lay['racks'][0]['size'][0] == 3.0 and lay['racks'][0]['size'][2] == 1.2
    assert {l['kind'] for l in lay['locations']} == {'SHELF', 'PACKING', 'INBOUND', 'OUTBOUND'}


def test_racking_bays_infeasible_building():
    with pytest.raises(ValueError):
        racking_bays('Too small', 5, 5, {'n_aisles': 2, 'bays_per_aisle': 4, 'aisle_width_m': 2.0})
    with pytest.raises(ValueError):
        racking_bays('Zero', 30, 20, {'n_aisles': 0, 'bays_per_aisle': 4})


def test_multifloor_lift_serves_all_floors_and_clearance():
    lay = multifloor_with_lift('MF', 30, 24, {'floors': [0, 6], 'lift_cell': [6, 6],
                                              'n_aisles': 1, 'bays_per_aisle': 4})
    assert validate_geometry(lay) == []
    rep = validate_layout(lay)
    assert rep['ok'] is True, rep['issues']
    lift = lay['lifts'][0]
    assert lift['floors'] == [1, 2]
    assert [f['elevation'] for f in lay['floors']] == [0, 6]
    # no rack intersects the shaft rect expanded by 2m clearance
    cs = lay['grid']['cell_size']
    mx, mz = (lift['cell'][0] + 0.5) * cs, (lift['cell'][1] + 0.5) * cs
    shaft = (mx - 1.4 - 2.0, mz - 1.9 - 2.0, mx + 1.4 + 2.0, mz + 1.9 + 2.0)
    for rack in lay['racks']:
        x, _, z = rack['position']; w, _, d = rack['size']
        assert not (x + w > shaft[0] and x < shaft[2] and z + d > shaft[1] and z < shaft[3]), \
            f'rack {rack["id"]} violates lift clearance'
    # landing cells walkable adjacent to shaft on BOTH floors
    from app.sim.navgrid import build_nav_grid
    for fid in (1, 2):
        g = build_nav_grid(lay, fid)
        c0, r0 = int((mx - 1.4) / cs), int((mz - 1.9) / cs)
        c1, r1 = int((mx + 1.4) / cs), int((mz + 1.9) / cs)
        ring = ([(c0 - 1, r) for r in range(r0 - 1, r1 + 2)] + [(c1 + 1, r) for r in range(r0 - 1, r1 + 2)] +
                [(c, r0 - 1) for c in range(c0, c1 + 1)] + [(c, r1 + 1) for c in range(c0, c1 + 1)])
        walkable = [g.cells[r * g.cols + c] == 0 for c, r in ring if 0 <= c < g.cols and 0 <= r < g.rows]
        assert any(walkable), f'no walkable lift landing on floor {fid}'


def test_conveyor_loop_shape_and_band():
    lay = conveyor_loop('Loop', 30, 20, {'loop_w_m': 16, 'loop_d_m': 8, 'bays_per_aisle': 2})
    assert validate_geometry(lay) == []
    rep = validate_layout(lay)
    assert rep['ok'] is True, rep['issues']
    conv = lay['conveyors'][0]
    assert len(conv['path']) == 5  # ring with a gap: interior stays reachable
    # band blocked: sample 3 cells along the top edge are blocked
    from app.sim.navgrid import build_nav_grid
    g = build_nav_grid(lay, 1)
    cs = g.cell_size
    x0, z0 = conv['path'][0]
    for frac in (0.3, 0.5, 0.8):
        x = x0 + 16 * frac
        c, r = int(x / cs), int(z0 / cs)
        assert g.cells[r * g.cols + c] == 1, f'conveyor band open at x={x}'
    # racks exist inside the ring
    assert len(lay['racks']) >= 1


def test_assert_template_valid_helper():
    lay = racking_bays('OK', 30, 20, {'n_aisles': 2, 'bays_per_aisle': 4})
    assert_template_valid(lay)  # no raise

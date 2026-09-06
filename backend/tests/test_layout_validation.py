"""Tests for runtime layout validation (operational refs, connectivity, clearance)."""
import pytest

from app.layout_geometry import empty_layout
from app.layout_validation import validate_layout


def _layout(width=30, depth=20, cell=0.5):
    return empty_layout('Test', width, depth, 6, cell)


def _loc(i, kind, x, z, floor=1):
    return {'id': f'{kind}-{i:03d}', 'kind': kind, 'zone': 'A', 'floor': floor,
            'level_range': [1, 2], 'access_point': [x, z]}


def _charger(i, x, z):
    # access point offset from the blocked 0.9x0.9m station rect, like the demo layout
    return {'id': f'CHG-{i:02d}', 'zone': 'C', 'position': [x, 0, z], 'heading': 0,
            'power_kw': 3.0, 'access_point': [x, z + 0.8]}


def _codes(report):
    return [i['code'] for i in report['issues']]


def test_empty_layout_ok_with_warnings():
    rep = validate_layout(_layout())
    assert rep['ok'] is True
    assert _codes(rep) == ['op_missing'] * 4  # SHELF/PACKING/INBOUND/OUTBOUND absent


def test_valid_layout_passes():
    lay = _layout()
    # keep every access point well away from any rack footprint edge
    lay['racks'] = [
        {'id': 'R1', 'zone': 'A', 'position': [5, 0, 5], 'size': [3, 0, 1.2], 'rotation': 0,
         'levels': 4, 'model': 'rack_double', 'blocks_grid': True, 'floor': 1},
    ]
    lay['locations'] = [_loc(1, 'SHELF', 3, 12), _loc(1, 'PACKING', 25, 15),
                        _loc(1, 'INBOUND', 2, 2), _loc(1, 'OUTBOUND', 28, 18)]
    lay['charging_stations'] = [_charger(1, 15, 10)]
    rep = validate_layout(lay)
    assert rep['ok'] is True, rep['issues']
    assert rep['issues'] == []


def test_robots_without_charger_is_error():
    lay = _layout()
    lay['spawn']['robots'] = [{'id': 'R1', 'position': [5, 0, 5], 'heading': 0, 'battery': 80, 'floor': 1}]
    rep = validate_layout(lay)
    assert rep['ok'] is False
    assert 'op_missing' in _codes(rep)


def test_disconnected_floor_reports_unreachable_region():
    lay = _layout(width=40, depth=10)
    # vertical wall of obstacles across the whole depth, splitting the floor
    wall = [{'id': f'W{i}', 'rect': [20, i * 2.5, 20.5, i * 2.5 + 2.5]} for i in range(4)]
    lay['obstacles'] = wall
    rep = validate_layout(lay)
    assert rep['ok'] is False
    assert 'unreachable_region' in _codes(rep)


def test_isolated_operational_point():
    lay = _layout(width=40, depth=10)
    wall = [{'id': f'W{i}', 'rect': [20, i * 2.5, 20.5, i * 2.5 + 2.5]} for i in range(4)]
    lay['obstacles'] = wall
    lay['locations'] = [_loc(1, 'PACKING', 25, 5)]  # right side, cut off by wall
    rep = validate_layout(lay)
    assert 'isolated_point' in _codes(rep)


def test_clearance_failure_narrow_corridor():
    lay = _layout(width=20, depth=6, cell=0.5)
    # two rack rows leaving a 0.6m gap: 0.35m robot clearance fails
    lay['racks'] = [
        {'id': 'R1', 'zone': 'A', 'position': [5, 0, 0], 'size': [3, 0, 2.4], 'rotation': 0,
         'levels': 4, 'model': 'rack_double', 'blocks_grid': True, 'floor': 1},
        {'id': 'R2', 'zone': 'A', 'position': [5, 0, 3.0], 'size': [3, 0, 2.4], 'rotation': 0,
         'levels': 2, 'model': 'rack_double', 'blocks_grid': True, 'floor': 1},
    ]
    lay['locations'] = [_loc(1, 'PACKING', 6.5, 2.7, floor=1)]
    lay['charging_stations'] = [_charger(1, 1, 3)]
    rep = validate_layout(lay, robot_clearance_m=0.35)
    assert 'clearance_insufficient' in _codes(rep), rep['issues']


def test_multifloor_lift_landings_connected():
    lay = _layout(width=30, depth=20)
    lay['floors'] = [
        {'id': 1, 'name': 'Ground', 'elevation': 0},
        {'id': 2, 'name': 'Mezz', 'elevation': 6, 'footprint': [[5, 5], [25, 5], [25, 15], [5, 15]]},
    ]
    lay['lifts'] = [{'id': 'LIFT-1', 'cell': [14, 9], 'floors': [1, 2], 'ride_ticks': 60}]
    lay['locations'] = [_loc(1, 'SHELF', 10, 10, floor=2), _loc(1, 'PACKING', 28, 18, floor=1)]
    rep = validate_layout(lay)
    assert rep['ok'] is True, rep['issues']


def test_no_floors_or_zero_dims_error():
    rep = validate_layout({'size': {'width': 0, 'depth': 0}, 'floors': []})
    assert rep['ok'] is False
    assert rep['issues'][0]['code'] in ('document', 'no_floors')


def test_degenerate_no_size():
    rep = validate_layout({})
    assert rep['ok'] is False
    assert rep['issues'][0]['code'] == 'document'

from copy import deepcopy

import pytest

from app.layout_geometry import empty_layout, resize_layout, validate_geometry


def test_resize_preserves_physical_equipment_and_reports_clipping():
    layout = empty_layout('Warehouse', 100, 70, 10)
    layout['racks'] = [{'id': 'rack', 'position': [80, 0, 10], 'size': [5, 4, 2], 'rotation': 0}]
    before = deepcopy(layout)
    expanded = resize_layout(layout, 120, 90, 10)
    assert expanded['racks'] == before['racks']
    assert validate_geometry(expanded) == []
    reduced = resize_layout(layout, 60, 40, 10)
    assert reduced['racks'] == before['racks']
    assert 'outside_floor' in {i['code'] for i in validate_geometry(reduced)}
    assert layout == before


def test_concave_boundary_excludes_notch_and_rotation_is_checked():
    layout = empty_layout('L-shaped', 20, 20, 10, 0.5)
    layout['floors'][0]['footprint'] = [[0, 0], [20, 0], [20, 10], [10, 10], [10, 20], [0, 20]]
    layout['racks'] = [{'id': 'rack', 'position': [15, 0, 15], 'size': [2, 2, 2], 'rotation': 0}]
    assert any(i['code'] == 'outside_floor' for i in validate_geometry(layout))
    layout['racks'][0].update(position=[1, 0, 1], rotation=90)
    assert any(i['code'] == 'outside_floor' for i in validate_geometry(layout))
    layout['racks'][0].update(position=[5, 0, 5])
    assert validate_geometry(layout) == []


@pytest.mark.parametrize('width', [0, -1, float('inf'), float('nan'), True])
def test_invalid_dimensions(width):
    with pytest.raises(ValueError):
        empty_layout('Invalid', width, 20, 10)


def test_grid_limits_and_rounding():
    assert empty_layout('Fractional', 10.1, 10.1, 5, 0.5)['grid']['cols'] == 21
    with pytest.raises(ValueError):
        empty_layout('Too large', 1000, 1000, 10, 0.1)


@pytest.mark.parametrize('key,value', [
    ('racks', None), ('floors', {}), ('zones', [1]), ('spawn', None),
    ('floors', [{'id': [], 'elevation': 0}]),
    ('racks', [{'id': [], 'position': [1, 0, 1], 'size': [1, 1, 1]}]),
    ('racks', [{'id': 'r', 'floor': [], 'position': [1, 0, 1], 'size': [1, 1, 1]}]),
    ('zones', [{'id': 'z', 'polygon': [[0, 0], [1, float('nan')], [1, 1]]}]),
    ('conveyors', [{'id': 'c', 'path': [[1, 1]], 'width': 1}]),
    ('locations', [{'id': 'l'}]),
])
def test_malformed_geometry_produces_issues_not_exceptions(key, value):
    layout = empty_layout('Warehouse', 20, 20, 10)
    layout[key] = value
    assert validate_geometry(layout)


def test_points_conveyors_and_multifloor_lifts_use_physical_coordinates():
    layout = empty_layout('Warehouse', 20, 20, 10, 0.5)
    layout['floors'].append({'id': 2, 'name': 'Upper', 'elevation': 5})
    layout['lifts'] = [{'id': 'lift', 'cell': [30, 30], 'floors': [1, 2], 'ride_ticks': 10}]
    layout['spawn']['robots'] = [{'id': 'robot', 'position': [1, 0, 1]}]
    layout['conveyors'] = [{'id': 'belt', 'path': [[2, 2], [5, 2]], 'width': 1}]
    assert validate_geometry(layout) == []
    layout['spawn']['robots'][0]['position'] = [21, 0, 1]
    layout['conveyors'][0]['path'] = [[2, 0], [5, 0]]
    layout['lifts'][0]['cell'] = [40, 0]
    paths = {i['path'] for i in validate_geometry(layout)}
    assert {'spawn.robots.0.position', 'conveyors.0', 'lifts.0'} <= paths


def test_column_bases_and_upper_floor_elevation_are_checked():
    layout = empty_layout('Warehouse', 20, 20, 10)
    layout['columns'] = [[0, 0]]
    layout['floors'].append({'id': 2, 'name': 'Upper', 'elevation': 5})
    layout['racks'] = [{'id': 'rack', 'floor': 2, 'position': [2, 0, 2], 'size': [2, 3, 2]}]
    paths = {i['path'] for i in validate_geometry(layout)}
    assert {'columns.0', 'racks.0'} <= paths
    layout['columns'] = [[1, 1]]
    layout['racks'][0]['position'][1] = 5
    assert validate_geometry(layout) == []


def test_conveyor_end_envelope_cannot_extend_beyond_floor():
    layout = empty_layout('Warehouse', 20, 20, 10)
    layout['conveyors'] = [{'id': 'c', 'path': [[0, 5], [5, 5]], 'width': 1}]
    assert any(i['path'] == 'conveyors.0' and i['code'] == 'outside_floor' for i in validate_geometry(layout))
    layout['conveyors'][0]['path'][0][0] = 0.5
    assert validate_geometry(layout) == []

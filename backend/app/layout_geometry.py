"""Physical layout operations. Coordinates and dimensions are always metres."""
from copy import deepcopy
import math
import uuid

from shapely.affinity import rotate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.validation import explain_validity


COLLECTIONS = ('zones', 'docks', 'racks', 'conveyors', 'stations',
               'charging_stations', 'parking', 'restricted_areas', 'walkways',
               'cameras', 'sensors', 'locations', 'obstacles', 'lifts')


def dimensions(width: float, depth: float, height: float, cell_size: float):
    values = (width, depth, height, cell_size)
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError('Dimensions and cell size must be finite positive numbers')
    cols, rows = math.ceil(width / cell_size), math.ceil(depth / cell_size)
    if cols * rows > 1_000_000:
        raise ValueError('Navigation grid exceeds 1,000,000 cells per floor')
    return {'width': width, 'depth': depth, 'height': height}, {
        'cell_size': cell_size, 'cols': cols, 'rows': rows,
    }


def empty_layout(name: str, width: float, depth: float, height: float,
                 cell_size: float = 1.0) -> dict:
    size, grid = dimensions(width, depth, height, cell_size)
    return {
        'schema_version': '1.0', 'id': uuid.uuid4().hex, 'name': name,
        'units': 'm', 'size': size, 'grid': grid,
        'floors': [{'id': 1, 'name': 'Ground floor', 'elevation': 0}],
        **{key: [] for key in COLLECTIONS}, 'columns': [], 'spawn': {'robots': []},
    }


def resize_layout(document: dict, width: float, depth: float, height: float) -> dict:
    result = deepcopy(document)
    result['size'], result['grid'] = dimensions(width, depth, height, document['grid']['cell_size'])
    return result


def validate_geometry(document: dict) -> list[dict]:
    """Report building/equipment issues; navigation connectivity is checked separately."""
    issues = []

    def issue(path, code, message):
        issues.append({'path': path, 'code': code, 'message': message, 'severity': 'error'})

    def finite(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    def vector(value, length):
        return isinstance(value, (list, tuple)) and len(value) == length and all(finite(v) for v in value)

    if not isinstance(document, dict):
        issue('', 'document', 'Layout must be an object')
        return issues
    if document.get('schema_version') != '1.0':
        issue('schema_version', 'schema_version', 'Supported layout schema is 1.0')
    for key in ('id', 'name'):
        if not isinstance(document.get(key), str) or not document[key].strip():
            issue(key, 'required', 'A nonempty string is required')
    # Reject malformed collection containers before any geometry operations.
    for key in ('floors', *COLLECTIONS):
        if not isinstance(document.get(key), list):
            issue(key, 'collection', 'An array of objects is required')
        elif any(not isinstance(item, dict) for item in document[key]):
            issue(key, 'collection', 'Every entry must be an object')
    spawn = document.get('spawn')
    if not isinstance(spawn, dict) or not isinstance(spawn.get('robots'), list) or any(
        not isinstance(robot, dict) for robot in spawn.get('robots', [])
    ):
        issue('spawn.robots', 'collection', 'An array of robot objects is required')
    if issues:
        return issues
    try:
        size = document['size']
        _, grid = dimensions(size['width'], size['depth'], size['height'], document['grid']['cell_size'])
        if grid != document['grid']:
            issue('grid', 'grid_dimensions', 'Grid dimensions must be derived from the building dimensions')
        boundary = box(0, 0, size['width'], size['depth'])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        issue('size', 'dimensions', str(exc))
        return issues
    if document.get('units') != 'm':
        issue('units', 'units', 'Convert imported coordinates to metres first')
    floors = {}
    for index, floor in enumerate(document.get('floors', [])):
        path = f'floors.{index}'
        try:
            fid = floor['id']
            if not isinstance(fid, int) or isinstance(fid, bool) or fid < 1:
                raise ValueError('Invalid floor ID')
            if not finite(floor.get('elevation')) or not 0 <= floor['elevation'] < size['height']:
                issue(path + '.elevation', 'height', 'Floor elevation must be within the building height')
            if floor.get('footprint') is not None and (
                not isinstance(floor['footprint'], list) or len(floor['footprint']) < 3
                or not all(vector(p, 2) for p in floor['footprint'])
            ):
                raise ValueError('Invalid floor footprint')
            if fid in floors:
                issue(path, 'duplicate_id', 'Floor ID must be unique')
            footprint = Polygon(floor['footprint']) if floor.get('footprint') else boundary
            if not footprint.is_valid or footprint.area <= 0:
                issue(path, 'invalid_polygon', explain_validity(footprint))
                continue
            if not boundary.covers(footprint):
                issue(path, 'outside_building', 'Floor footprint extends outside the building')
            floors[fid] = footprint
        except (KeyError, TypeError, ValueError, OverflowError):
            issue(path, 'invalid_floor', 'Floor needs an ID and a valid polygon')
    if not floors:
        issue('floors', 'missing_floor', 'At least one valid floor is required')
    elevations = {floor['id']: floor.get('elevation', 0) for floor in document['floors']
                  if isinstance(floor.get('id'), int) and finite(floor.get('elevation'))}
    columns = document.get('columns', [])
    if not isinstance(columns, list):
        issue('columns', 'collection', 'Columns must be an array of physical coordinates')
    else:
        for index, position in enumerate(columns):
            if not vector(position, 2):
                issue(f'columns.{index}', 'invalid_geometry', 'Column needs two finite coordinates')
            elif 1 not in floors or not floors[1].covers(box(
                position[0] - 0.45, position[1] - 0.45,
                position[0] + 0.45, position[1] + 0.45,
            )):
                issue(f'columns.{index}', 'outside_floor', 'Column base extends outside the ground floor')
    collections = {key: document[key] for key in COLLECTIONS}
    collections['spawn.robots'] = spawn['robots']
    for collection, items in collections.items():
        seen = set()
        for index, item in enumerate(items):
            path = f'{collection}.{index}'
            try:
                if not isinstance(item.get('id'), str) or not item['id'].strip():
                    raise ValueError('Invalid object ID')
                if item['id'] in seen:
                    issue(path, 'duplicate_id', 'Object ID must be present and unique within its collection')
                seen.add(item.get('id'))
                floor = floors.get(item.get('floor', 1))
                if floor is None:
                    issue(path, 'unknown_floor', 'Object references an unknown floor')
                    continue
                shape = None
                if collection == 'lifts':
                    cell = item.get('cell')
                    served = item.get('floors')
                    if not vector(cell, 2) or any(int(c) != c for c in cell):
                        raise ValueError('Invalid lift cell')
                    if not isinstance(served, list) or len(served) < 2 or any(
                        not isinstance(fid, int) or isinstance(fid, bool) or fid not in floors for fid in served
                    ) or len(set(served)) != len(served):
                        raise ValueError('Invalid lift floors')
                    if not finite(item.get('ride_ticks')) or item['ride_ticks'] < 1:
                        raise ValueError('Invalid lift duration')
                    x, z = ((c + 0.5) * grid['cell_size'] for c in cell)
                    if any(not floors[fid].covers(Point(x, z)) for fid in served):
                        issue(path, 'outside_floor', 'Lift cell is outside a served floor')
                    continue
                if collection == 'racks':
                    if not vector(item.get('position'), 3) or not vector(item.get('size'), 3) or not finite(item.get('rotation', 0)):
                        raise ValueError('Invalid rack geometry')
                    x, y, z = item['position']
                    w, h, d = item['size']
                    if any(not math.isfinite(v) for v in (x, y, z, w, h, d, item.get('rotation', 0))) or min(w, h, d) <= 0:
                        raise ValueError('Invalid rack dimensions')
                    shape = rotate(box(x, z, x+w, z+d), item.get('rotation', 0), origin=(x, z))
                    if y < elevations.get(item.get('floor', 1), 0) or y+h > size['height']:
                        issue(path, 'height', 'Rack extends beyond the building height')
                elif 'rect' in item:
                    if not vector(item['rect'], 4):
                        raise ValueError('Invalid rectangle')
                    x0, z0, x1, z1 = item['rect']
                    if not all(math.isfinite(v) for v in (x0, z0, x1, z1)) or x1 <= x0 or z1 <= z0:
                        raise ValueError('Invalid rectangle')
                    shape = box(x0, z0, x1, z1)
                elif 'polygon' in item:
                    if not isinstance(item['polygon'], list) or len(item['polygon']) < 3 or not all(vector(p, 2) for p in item['polygon']):
                        raise ValueError('Invalid polygon')
                    shape = Polygon(item['polygon'])
                elif collection == 'conveyors':
                    if not isinstance(item.get('path'), list) or len(item['path']) < 2 or not all(vector(p, 2) for p in item['path']):
                        raise ValueError('Invalid conveyor path')
                    if not finite(item.get('width')) or item['width'] <= 0:
                        raise ValueError('Invalid conveyor width')
                    line = LineString(item['path'])
                    if line.length <= 0:
                        raise ValueError('Empty conveyor path')
                    # Match the square-ended segment bodies used by navigation.
                    shape = unary_union([
                        LineString([a, b]).buffer(item['width'] / 2, cap_style='square')
                        for a, b in zip(item['path'], item['path'][1:]) if a != b
                    ])
                elif collection not in ('charging_stations', 'cameras', 'sensors', 'locations', 'spawn.robots'):
                    raise ValueError('Missing object geometry')
                for key, length in (('position', 3), ('access_point', 2), ('door', 2)):
                    if key not in item:
                        if (key == 'position' and collection in ('charging_stations', 'cameras', 'sensors', 'spawn.robots')) or (key == 'access_point' and collection == 'locations'):
                            raise ValueError('Missing object coordinates')
                        continue
                    if not vector(item[key], length):
                        raise ValueError('Invalid object coordinates')
                    point = item[key]
                    if not floor.covers(Point(point[0], point[-1])):
                        issue(path + '.' + key, 'outside_floor', 'Point lies outside its floor boundary')
                    if length == 3 and not elevations.get(item.get('floor', 1), 0) <= point[1] <= size['height']:
                        issue(path + '.' + key, 'height', 'Point lies outside the building height')
                if shape is not None:
                    if not shape.is_valid or shape.area <= 0:
                        issue(path, 'invalid_polygon', 'Object geometry is invalid')
                    elif not floor.covers(shape):
                        issue(path, 'outside_floor', 'Object extends outside its floor boundary')
            except (KeyError, TypeError, ValueError, OverflowError):
                issue(path, 'invalid_geometry', 'Object coordinates or dimensions are invalid')
    return issues

"""Physical rasterization mirrored by frontend/src/layout/navgrid.ts."""
from __future__ import annotations
import json
import math
from pathlib import Path
from shapely.affinity import rotate
from shapely.geometry import Polygon, box
from .astar import NavGrid


def load_layout(path=None):
    with open(Path(path) if path else Path(__file__).resolve().parent.parent / 'warehouse_layout.json', encoding='utf-8') as f:
        return json.load(f)


def build_nav_grid(layout, floor=1):
    cols, rows, cs = (layout['grid'][k] for k in ('cols', 'rows', 'cell_size'))
    cells = bytearray(cols * rows)
    epsilon = cs * cs * 1e-9

    def paint(shape, value):
        x0, z0, x1, z1 = shape.bounds
        rectangular = shape.equals(box(x0, z0, x1, z1))
        for r in range(max(0, math.floor(z0/cs)), min(rows, math.ceil(z1/cs))):
            for c in range(max(0, math.floor(x0/cs)), min(cols, math.ceil(x1/cs))):
                if rectangular or shape.intersection(box(c*cs, r*cs, (c+1)*cs, (r+1)*cs)).area > epsilon:
                    cells[r*cols+c] = value

    def rect(x0, z0, x1, z1):
        paint(box(x0, z0, x1, z1), 1)

    def on_floor(item):
        return item.get('floor', 1) == floor

    for w in layout.get('walkways', []):
        if on_floor(w):
            paint(Polygon(w['polygon']), 2 if w.get('robots_allowed', True) else 1)
    for rack in layout.get('racks', []):
        if rack.get('blocks_grid', True) and on_floor(rack):
            x, _, z = rack['position']; w, _, d = rack['size']
            paint(rotate(box(x,z,x+w,z+d), rack.get('rotation', 0), origin=(x,z)), 1)
    for conveyor in layout.get('conveyors', []):
        if conveyor.get('blocks_grid', True) and on_floor(conveyor):
            for (ax,az), (bx,bz) in zip(conveyor['path'], conveyor['path'][1:]):
                length = math.hypot(bx-ax,bz-az)
                if not length:
                    continue
                ux, uz, h = (bx-ax)/length, (bz-az)/length, conveyor['width']/2
                # Square ends match the existing conveyor equipment envelope.
                paint(Polygon([(ax-ux*h-uz*h,az-uz*h+ux*h), (bx+ux*h-uz*h,bz+uz*h+ux*h),
                               (bx+ux*h+uz*h,bz+uz*h-ux*h), (ax-ux*h+uz*h,az-uz*h-ux*h)]), 1)
    for item in layout.get('restricted_areas', []):
        if on_floor(item) and not item['robots_allowed']:
            rect(*item['rect'])
    for key in ('stations', 'obstacles'):
        for item in layout.get(key, []):
            if on_floor(item):
                rect(*item['rect'])
    if floor == 1:
        for x,z in layout.get('columns', []):
            rect(x-.45,z-.45,x+.45,z+.45)
    for item in layout.get('charging_stations', []):
        if on_floor(item):
            x,_,z = item['position']; rect(x-.45,z-.4,x+.45,z+.5)
    for lift in layout.get('lifts', []):
        if floor in lift['floors']:
            x,z = ((v+.5)*cs for v in lift['cell'])
            rect(x-1.4,z-1.9,x+1.4,z+1.9)
    building = box(0,0,layout['size']['width'],layout['size']['depth'])
    level = next((f for f in layout.get('floors', []) if f['id'] == floor), None)
    if level is None:
        cells[:] = bytes([1])*len(cells)
    else:
        boundary = building.intersection(Polygon(level['footprint'])) if level.get('footprint') else building
        rectangular = boundary.equals(building)
        # Boundary is last: walkways cannot reopen missing floor cells.
        for r in range(rows):
            for c in range(cols):
                inside = (c+1)*cs <= layout['size']['width'] and (r+1)*cs <= layout['size']['depth']
                if inside and not rectangular:
                    inside = box(c*cs,r*cs,(c+1)*cs,(r+1)*cs).difference(boundary).area <= epsilon
                if not inside:
                    cells[r*cols+c] = 1
    return NavGrid(cols=cols, rows=rows, cells=cells, cell_size=cs)

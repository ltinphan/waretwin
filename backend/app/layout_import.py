"""Customer plan imports: DXF (unit-confirmed), PDF plans (calibrated), image calibration.

Best-effort extraction with structured warnings; callers confirm units/scale.
"""
from __future__ import annotations

import base64
import io
import math

import ezdxf
import pymupdf

from app.layout_geometry import empty_layout

UNIT_SCALE = {'mm': 0.001, 'cm': 0.01, 'm': 1.0, 'in': 0.0254, 'ft': 0.3048}
_HEADER_UNITS = {0: 'unknown', 1: 'in', 2: 'ft', 4: 'mm', 5: 'cm', 6: 'm'}


def _to_layout(name: str, width_m: float, depth_m: float) -> dict:
    return empty_layout(name, round(width_m, 4), round(depth_m, 4), 4.0, 1.0)


def _classify(polygons, width_m, depth_m):
    """Largest polygon = floor boundary; the rest become obstacles/walkways."""
    warnings = []
    if not polygons:
        return None, [], warnings
    ordered = sorted(polygons, key=lambda p: math.hypot(p[2] - p[0], p[3] - p[1]) * -1)
    bx0, bz0, bx1, bz1 = ordered[0]
    obstacles, walkways = [], []
    for i, (x0, z0, x1, z1) in enumerate(ordered[1:]):
        if abs((x1 - x0) - (z1 - z0)) < 1e-6:  # square: probably a rack footprint
            obstacles.append({'id': f'IMP-O{i+1:02d}', 'rect': [x0, z0, x1, z1]})
        else:
            walkways.append({'id': f'IMP-W{i+1:02d}',
                             'polygon': [[x0, z0], [x1, z0], [x1, z1], [x0, z1]],
                             'robots_allowed': False})
    return (bx0, bz0, bx1, bz1), (obstacles, walkways), warnings


def import_dxf(data: bytes, *, units: str) -> dict:
    if units not in UNIT_SCALE:
        raise ValueError(f'units must be one of {sorted(UNIT_SCALE)}')
    warnings = []
    if isinstance(data, (bytes, bytearray)):
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            text = data.decode('latin-1')
    else:
        text = data
    doc = ezdxf.read(io.StringIO(text))
    msp = doc.modelspace()
    scale = UNIT_SCALE[units]

    header_raw = doc.header.get('$INSUNITS', 0)
    header_units = _HEADER_UNITS.get(header_raw, 'unknown')
    if header_units not in ('unknown', units):
        warnings.append(f'units_mismatch: header {header_units} vs given {units}')

    polys = []
    for entity in msp:
        kind = entity.dxftype()
        if kind == 'LWPOLYLINE' and entity.closed:
            pts = [(p[0] * scale, p[1] * scale) for p in entity.get_points('xy')]
        elif kind == 'POLYLINE' and entity.is_closed:
            pts = [(v.dxf.location.x * scale, v.dxf.location.y * scale) for v in entity.vertices]
        elif kind in ('LINE',):  # ponytail: 4-LINE rectangles only, loose ends ignored
            continue
        else:
            continue
        if len(pts) >= 3:
            xs, zs = [p[0] for p in pts], [p[1] for p in pts]
            polys.append((min(xs), min(zs), max(xs), max(zs)))
    if not polys:
        warnings.append('no_entities: no closed polylines found')
        return {'layout': _to_layout('Imported DXF', 10, 10),
                'warnings': warnings, 'detected_units': header_units}

    x0, z0, x1, z1 = (min(p[0] for p in polys), min(p[1] for p in polys),
                      max(p[2] for p in polys), max(p[3] for p in polys))
    width, depth = x1 - x0, z1 - z0
    if units == 'm' and max(width, depth) > 1000:
        warnings.append(f'suspected_mm_scale: extents {width:.0f}m x {depth:.0f}m with units=m'
                        ' - re-import with units=mm')
        return {'layout': _to_layout('Imported DXF (suspected mm)', 10, 10),
                'warnings': warnings, 'detected_units': header_units}
    layout = _to_layout('Imported DXF', width, depth)
    if x0 != 0 or z0 != 0:  # shift everything into the 0,0-origin building
        dx, dz = -x0, -z0
        polys = [(p[0] + dx, p[1] + dz, p[2] + dx, p[3] + dz) for p in polys]
    _, (obstacles, walkways), _ = _classify(polys, width, depth)
    layout['obstacles'] = obstacles
    layout['walkways'] = walkways
    return {'layout': layout, 'warnings': warnings, 'detected_units': header_units}


def import_pdf_plan(data: bytes, *, scale_m_per_unit: float) -> dict:
    if not isinstance(scale_m_per_unit, (int, float)) or scale_m_per_unit <= 0:
        raise ValueError('scale_m_per_unit must be a positive number')
    warnings = []
    pdf = pymupdf.open(stream=data, filetype='pdf')
    page = pdf[0]
    page_w_m, page_h_m = page.rect.width * scale_m_per_unit, page.rect.height * scale_m_per_unit

    polys = []
    for drawing in page.get_drawings():
        for item in drawing['items']:
            if item[0] == 're':
                r = item[1]
                polys.append((r.x0 * scale_m_per_unit,
                              (page.rect.height - r.y1) * scale_m_per_unit,
                              r.x1 * scale_m_per_unit,
                              (page.rect.height - r.y0) * scale_m_per_unit))
            elif item[0] == 'qu' and len(item[1]) == 4:
                pts = [(p.x * scale_m_per_unit, (page.rect.height - p.y) * scale_m_per_unit) for p in item[1]]
                xs, zs = [p[0] for p in pts], [p[1] for p in pts]
                polys.append((min(xs), min(zs), max(xs), max(zs)))
    if polys:
        x0, z0, x1, z1 = (min(p[0] for p in polys), min(p[1] for p in polys),
                          max(p[2] for p in polys), max(p[3] for p in polys))
        layout = _to_layout('Imported PDF', x1 - x0, z1 - z0)
        if x0 != 0 or z0 != 0:
            polys = [(p[0] - x0, p[1] - z0, p[2] - x0, p[3] - z0) for p in polys]
        _, (obstacles, walkways), _ = _classify(polys, x1 - x0, z1 - z0)
        layout['obstacles'] = obstacles
        layout['walkways'] = walkways
        return {'layout': layout, 'warnings': warnings, 'page_size_m': [page_w_m, page_h_m]}

    images = page.get_images(full=True)
    if images:  # raster fallback: embed as a background the editor renders
        xref = images[0][0]
        raw = pdf.extract_image(xref)['image']
        layout = _to_layout('Imported PDF plan', page_w_m, page_h_m)
        layout['background_image'] = {
            'data_b64': base64.b64encode(raw).decode('ascii'),
            'page_size_m': [page_w_m, page_h_m],
        }
        return {'layout': layout, 'warnings': ['raster_fallback: no vector drawings, '
                                               'embedded page image as background'],
                'page_size_m': [page_w_m, page_h_m]}
    warnings.append('empty_page: no vector drawings or images')
    return {'layout': _to_layout('Imported PDF', page_w_m, page_h_m),
            'warnings': warnings, 'page_size_m': [page_w_m, page_h_m]}


def calibrate_image(image: bytes, *, known_length_px: int, known_length_m: float) -> dict:
    if (not isinstance(known_length_px, (int, float)) or known_length_px <= 0
        or not isinstance(known_length_m, (int, float)) or known_length_m <= 0):
        raise ValueError('known length in pixels and metres must be positive')
    pix = pymupdf.Pixmap(image)  # positional: PNG/JPEG bytes
    m_per_px = known_length_m / known_length_px
    return {'m_per_px': m_per_px,
            'image_size_px': [pix.width, pix.height],
            'image_size_m': [pix.width * m_per_px, pix.height * m_per_px]}

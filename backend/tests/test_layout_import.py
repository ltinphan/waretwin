"""Tests for DXF/PDF/image imports with unit confirmation and calibration."""
import io

import ezdxf
import pymupdf
import pytest

from app.layout_geometry import validate_geometry
from app.layout_import import calibrate_image, import_dxf, import_pdf_plan


def _dxf_bytes(units_header=4, with_entities=True):
    doc = ezdxf.new('R2010', setup=True)
    doc.header['$INSUNITS'] = units_header  # 4 = mm
    if with_entities:
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 0), (5000, 0), (5000, 3000), (0, 3000)], close=True)
        msp.add_lwpolyline([(500, 500), (800, 500), (800, 800), (500, 800)], close=True)
        msp.add_lwpolyline([(1000, 500), (2500, 500), (2500, 700), (1000, 700)], close=True)
    sio = io.StringIO()
    doc.write(sio)
    return sio.getvalue().encode('utf-8')


def test_dxf_mm_import_geometry_and_units():
    out = import_dxf(_dxf_bytes(), units='mm')
    lay = out['layout']
    assert (lay['size']['width'], lay['size']['depth']) == (5.0, 3.0)
    assert len(lay['obstacles']) + len(lay['walkways']) == 2
    assert out['detected_units'] == 'mm'
    assert out['warnings'] == []
    assert validate_geometry(lay) == []


def test_dxf_unit_mismatch_and_scale_warnings():
    out = import_dxf(_dxf_bytes(), units='cm')  # header says mm
    assert any('units_mismatch' in w for w in out['warnings'])
    big = _dxf_bytes()
    out2 = import_dxf(big, units='m')  # 1000m-wide "building"
    assert any('suspected_mm_scale' in w for w in out2['warnings'])


def test_dxf_bad_units_and_empty_drawing():
    with pytest.raises(ValueError):
        import_dxf(_dxf_bytes(), units='furlongs')
    out = import_dxf(_dxf_bytes(with_entities=False), units='mm')
    assert any('no_entities' in w for w in out['warnings'])
    assert out['layout']['obstacles'] == []


def _pdf_vector_bytes():
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=120)  # points
    shape = page.new_shape()
    shape.draw_rect(pymupdf.Rect(10, 10, 190, 110))   # boundary 180x100pt
    shape.draw_rect(pymupdf.Rect(20, 20, 50, 50))      # square obstacle
    shape.finish(color=(0, 0, 0), width=1)
    shape.commit()
    return doc.tobytes()


def test_pdf_vector_import_with_calibration():
    out = import_pdf_plan(_pdf_vector_bytes(), scale_m_per_unit=0.05)  # 1pt = 0.05m
    lay = out['layout']
    assert (lay['size']['width'], lay['size']['depth']) == (9.0, 5.0)
    assert out['page_size_m'] == [10.0, 6.0]
    assert len(lay['obstacles']) == 1
    assert validate_geometry(lay) == []
    with pytest.raises(ValueError):
        import_pdf_plan(_pdf_vector_bytes(), scale_m_per_unit=0)


def _pdf_raster_bytes():
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 6))
    pix.clear_with(0)
    png = pix.tobytes('png')
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=120)
    page.insert_image(pymupdf.Rect(0, 0, 200, 120), stream=png)
    return doc.tobytes()


def test_pdf_raster_fallback_background():
    out = import_pdf_plan(_pdf_raster_bytes(), scale_m_per_unit=0.05)
    lay = out['layout']
    assert 'background_image' in lay
    assert len(lay['background_image']['data_b64']) > 0
    assert any('raster_fallback' in w for w in out['warnings'])


def test_pdf_empty_page():
    doc = pymupdf.open()
    doc.new_page(width=100, height=100)
    out = import_pdf_plan(doc.tobytes(), scale_m_per_unit=0.1)
    assert any('empty_page' in w for w in out['warnings'])


def test_image_calibration():
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 500, 400))
    pix.clear_with(0)
    out = calibrate_image(pix.tobytes('png'), known_length_px=500, known_length_m=25.0)
    assert out['m_per_px'] == 0.05
    assert out['image_size_px'] == [500, 400]
    assert out['image_size_m'] == [25.0, 20.0]
    with pytest.raises(ValueError):
        calibrate_image(pix.tobytes('png'), known_length_px=0, known_length_m=25.0)

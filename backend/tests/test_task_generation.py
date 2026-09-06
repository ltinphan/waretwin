"""Demo task generator must survive empty/custom layouts and keep demo RNG parity."""
import copy
import json
import os

import pytest

from app.layout_geometry import empty_layout
from app.sim.engine import SimEngine

DEMO = os.path.join(os.path.dirname(__file__), '..', 'app', 'warehouse_layout.json')


def _step(engine, ticks):
    for _ in range(ticks):
        engine.step()


def test_empty_layout_does_not_crash_task_generator():
    layout = empty_layout('Empty', 20, 20, 8)
    layout['spawn']['robots'] = [{'id': 'r1', 'position': [3, 0, 3], 'heading': 0, 'battery': 90}]
    engine = SimEngine(layout)
    _step(engine, 300)
    assert engine.state['robots']['r1']['status'] in ('IDLE', 'ACTIVE', 'WARNING')


def test_partial_layout_uses_available_categories_only():
    layout = empty_layout('Partial', 20, 20, 8)
    layout['locations'] = [
        {'id': 'sh1', 'kind': 'SHELF', 'name': 'S1', 'access_point': [5, 5], 'floor': 1},
        {'id': 'pk1', 'kind': 'PACKING', 'name': 'P1', 'access_point': [5, 10], 'floor': 1},
    ]
    layout['spawn']['robots'] = [{'id': 'r1', 'position': [4, 0, 4], 'heading': 0, 'battery': 90}]
    engine = SimEngine(layout)
    _step(engine, 200)
    kinds = {t['source'] for t in engine.state['tasks'].values()} | \
            {t['destination'] for t in engine.state['tasks'].values()}
    assert kinds <= {'sh1', 'pk1'}
    assert engine.state['tasks'], 'partial layout should still generate PICK tasks'


def test_demo_task_stream_is_unchanged():
    with open(DEMO) as f:
        demo = json.load(f)
    before = SimEngine(copy.deepcopy(demo))
    after = SimEngine(copy.deepcopy(demo))
    for _ in range(600):
        before.step()
        after.step()
    assert len(before.state['tasks']) == len(after.state['tasks'])
    assert list(before.state['tasks'].keys()) == list(after.state['tasks'].keys())
    for tid, t in before.state['tasks'].items():
        assert after.state['tasks'][tid]['source'] == t['source']
        assert after.state['tasks'][tid]['destination'] == t['destination']
        assert after.state['tasks'][tid]['type'] == t['type']
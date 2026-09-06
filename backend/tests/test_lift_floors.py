"""Lift state machine generalized beyond floors 1/2 (queues, doors, direction, platform y)."""
import pytest

from app.layout_geometry import empty_layout
from app.sim.engine import SimEngine


def multifloor_layout():
    layout = empty_layout('Multifloor', 30, 30, 14)
    layout['floors'] = [
        {'id': 1, 'name': 'Ground', 'elevation': 0},
        {'id': 3, 'name': 'Mid', 'elevation': 4},
        {'id': 5, 'name': 'Top', 'elevation': 8},
    ]
    layout['locations'] = [
        {'id': 'sh_g', 'kind': 'SHELF', 'name': 'G shelf', 'access_point': [6, 6], 'floor': 1},
        {'id': 'pk_3', 'kind': 'PACKING', 'name': 'F3 pack', 'access_point': [16, 6], 'floor': 3},
        {'id': 'pk_5', 'kind': 'PACKING', 'name': 'F5 pack', 'access_point': [16, 16], 'floor': 5},
        {'id': 'in_g', 'kind': 'INBOUND', 'name': 'G in', 'access_point': [6, 16], 'floor': 1},
        {'id': 'out_g', 'kind': 'OUTBOUND', 'name': 'G out', 'access_point': [6, 22], 'floor': 1},
    ]
    layout['lifts'] = [{'id': 'lift', 'cell': [11, 11], 'floors': [1, 3, 5], 'ride_ticks': 10}]
    layout['spawn']['robots'] = [{'id': 'r1', 'position': [8, 0, 8], 'heading': 0, 'battery': 95}]
    layout['charging_stations'] = []
    layout['zones'] = []
    layout['conveyors'] = []
    layout['cameras'] = []
    layout['sensors'] = []
    return layout


def run_task(engine, task):
    r = engine.state['robots']['r1']
    task['status'] = 'ASSIGNED'; task['assigned_robot'] = 'r1'; task['assigned_tick'] = engine.state['sim']['tick']
    r['current_task_id'] = task['id']
    engine._set_fsm(r, 'TASK_ASSIGNED')
    for _ in range(4000):
        engine.step()
        if engine.state['tasks'][task['id']]['status'] == 'COMPLETED':
            return True
    return False


def test_lift_runtime_supports_arbitrary_floors():
    engine = SimEngine(multifloor_layout())
    L = engine.state['lifts']['lift']
    assert set(L['queue'].keys()) == {'1', '3', '5'}
    assert L['door_state'] == {'1': 'CLOSED', '3': 'CLOSED', '5': 'CLOSED'}


@pytest.mark.parametrize('dest,dest_floor', [('pk_3', 3), ('pk_5', 5)])
def test_robot_completes_crossfloor_trip(dest, dest_floor):
    engine = SimEngine(multifloor_layout())
    task = engine.create_task('PICK', 'NORMAL', 'sh_g', dest)
    assert run_task(engine, task), (
        f"task to {dest} stuck: fsm={engine.state['robots']['r1']['fsm']} "
        f"stage={engine.state['robots']['r1']['lift_stage']} "
        f"lift={engine.state['lifts']['lift']['state']}")
    assert engine.state['robots']['r1']['floor'] == dest_floor


def test_lift_moves_down_from_higher_floor():
    """Lift resting at floor 5; a robot queues at floor 3 → lift must move DOWN (direction was hardcoded to ==2)."""
    engine = SimEngine(multifloor_layout())
    L = engine.state['lifts']['lift']
    L['floor'] = 5; L['y'] = 8
    task = engine.create_task('PICK', 'NORMAL', 'sh_g', 'pk_5')
    assert run_task(engine, task), 'task stuck'
    assert engine.state['robots']['r1']['floor'] == 5
    # The lift must have traveled 5 → 1 (downward) to collect the robot, then up to 5.
    assert L['trips'] >= 1
    assert L['floor'] == 5


def test_door_state_tracks_per_floor_keys():
    engine = SimEngine(multifloor_layout())
    L = engine.state['lifts']['lift']
    engine._open_lift_door(L, 3)
    assert L['door_state']['3'] == 'OPEN' and L['door_state']['1'] == 'CLOSED'
    assert L['door_f1'] == 'CLOSED' and L['door_f2'] == 'CLOSED'   # compat fields untouched for floor 3
    engine._close_lift_doors(L)
    assert all(v == 'CLOSED' for v in L['door_state'].values())
    engine._open_lift_door(L, 1)
    assert L['door_state']['1'] == 'OPEN' and L['door_f1'] == 'OPEN'   # compat fields still maintained for floors 1/2
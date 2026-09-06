import math
import pytest
from app.layout_geometry import empty_layout
from app.sim.astar import nearest_walkable
from app.sim.engine import SimEngine


def layout_at(cs):
    layout = empty_layout('Resolution', 24, 24, 10, cs)
    layout['spawn']['robots'] = [{'id': 'r', 'position': [3.2,0,3.2], 'heading': 0, 'battery': 100}]
    return layout


@pytest.mark.parametrize('cs', [.5, 1, 2])
def test_robot_routes_and_moves_in_metres_at_each_resolution(cs):
    engine = SimEngine(layout_at(cs))
    robot = engine.state['robots']['r']
    start = engine._cell_center(engine._to_cell(3.2,3.2))
    assert robot['position'] == [start[0],0,start[1]]
    assert nearest_walkable(engine.grid, 15.2, 3.2) == engine._to_cell(15.2,3.2)
    engine._plan_to(robot, engine.rt['r'], (15.2,3.2), 'TO_PICKUP')
    assert engine.rt['r'].target == engine._to_cell(15.2,3.2)
    assert robot['path']
    for _ in range(1200):
        engine._rebuild_occupancy()
        engine._move_along_path(robot, engine.rt['r'])
        assert all(math.isfinite(p) for p in robot['position'])
        if engine.rt['r'].target is None:
            break
    goal = engine._cell_center(engine._to_cell(15.2,3.2))
    # The engine marks a waypoint reached within its existing 8cm tolerance.
    assert math.hypot(robot['position'][0]-goal[0], robot['position'][2]-goal[1]) < .08
    assert robot['stats']['distance_m'] == pytest.approx(goal[0]-start[0], abs=.1)


@pytest.mark.parametrize('cs', [.5,1,2])
def test_lift_and_congestion_geometry_remain_in_metres(cs):
    layout=layout_at(cs)
    layout['floors'].append({'id':2,'name':'Upper','elevation':5})
    layout['spawn']['robots'][0].update(floor=2)
    layout['lifts']=[{'id':'lift','cell':[int(12/cs),int(12/cs)],'floors':[1,2],'ride_ticks':10}]
    layout['zones']=[{'id':'z','name':'Z','polygon':[[4,4],[8,4],[8,8],[4,8]],'color':'#ffffff'}]
    e=SimEngine(layout)
    assert e.state['robots']['r']['position'][1] == 5
    cabin=e._lift_cabin(layout['lifts'][0]); slot=e._lift_slot(layout['lifts'][0],0)
    assert cabin == (12+cs/2,12+cs/2)
    assert slot == (cabin[0]-4,cabin[1])
    e.blocked_zones.add('z')
    assert e._to_cell(5,5) in e._blocked_cells('r',1)
    assert e._to_cell(9,9) not in e._blocked_cells('r',1)
    e.congested_zones['z']={'level':1,'until':100}
    assert e._zone_speed_factor(e._to_cell(5,5),1) == pytest.approx(.3)
    assert e._zone_speed_factor(e._to_cell(9,9),1) == 1

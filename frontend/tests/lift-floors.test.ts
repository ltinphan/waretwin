import { expect, test } from 'vitest';
import { SimEngine } from '../src/simulation/engine';
import type { WarehouseLayout } from '../src/layout/types';
import demo from '../src/layout/warehouse_layout.json';

function multifloorLayout(): WarehouseLayout {
  const layout = structuredClone(demo) as WarehouseLayout;
  for (const key of ['lifts','columns','zones','docks','racks','conveyors','stations','charging_stations','parking','restricted_areas','walkways','cameras','sensors','locations','obstacles'] as const) layout[key]=[];
  layout.size={width:30,depth:30,height:14};
  layout.grid={cell_size:1,cols:30,rows:30};
  layout.floors=[
    {id:1,name:'Ground',elevation:0},
    {id:3,name:'Mid',elevation:4},
    {id:5,name:'Top',elevation:8},
  ];
  layout.lifts=[{id:'lift',cell:[11,11],floors:[1,3,5],ride_ticks:10}];
  layout.locations=[
    {id:'sh_g',kind:'SHELF',name:'G shelf',access_point:[6,6],floor:1},
    {id:'pk_3',kind:'PACKING',name:'F3 pack',access_point:[16,6],floor:3},
    {id:'pk_5',kind:'PACKING',name:'F5 pack',access_point:[16,16],floor:5},
    {id:'in_g',kind:'INBOUND',name:'G in',access_point:[6,16],floor:1},
    {id:'out_g',kind:'OUTBOUND',name:'G out',access_point:[6,22],floor:1},
  ] as never;
  layout.spawn={robots:[{id:'r1',position:[8,0,8],heading:0,battery:95}]};
  return layout;
}

function runTask(engine: SimEngine, source: string, dest: string): boolean {
  const r = engine.state.robots.r1;
  const task = engine['createTask']({ type: 'PICK', priority: 'NORMAL', source, destination: dest });
  task.status = 'ASSIGNED'; task.assigned_robot = r.id; task.assigned_tick = engine.state.sim.tick;
  r.current_task_id = task.id;
  engine['setFsm'](r, 'TASK_ASSIGNED');
  for (let i = 0; i < 4000; i++) {
    engine.step();
    if (engine.state.tasks[task.id].status === 'COMPLETED') return true;
  }
  return false;
}

test('lift runtime supports arbitrary floor ids', () => {
  const engine = new SimEngine(multifloorLayout());
  const L = engine.state.lifts.lift;
  expect(Object.keys(L.queue).sort()).toEqual(['1', '3', '5']);
  expect(L.door_state).toEqual({ '1': 'CLOSED', '3': 'CLOSED', '5': 'CLOSED' });
});

test.each([
  ['pk_3', 3],
  ['pk_5', 5],
])('robot completes cross-floor trip to floor %s', (dest, destFloor) => {
  const engine = new SimEngine(multifloorLayout());
  expect(runTask(engine, 'sh_g', dest)).toBe(true);
  expect(engine.state.robots.r1.floor).toBe(destFloor);
});

test('lift moves down from a higher floor (direction not hardcoded to 2)', () => {
  const engine = new SimEngine(multifloorLayout());
  const L = engine.state.lifts.lift;
  L.floor = 5; L.y = 8;
  expect(runTask(engine, 'sh_g', 'pk_5')).toBe(true);
  expect(engine.state.robots.r1.floor).toBe(5);
  expect(L.trips).toBeGreaterThanOrEqual(1);
  expect(L.floor).toBe(5);
});

test('door_state tracks per-floor keys; door_f1/f2 compat fields maintained', () => {
  const engine = new SimEngine(multifloorLayout());
  const L = engine.state.lifts.lift;
  engine['openLiftDoor'](L, 3);
  expect(L.door_state!['3']).toBe('OPEN');
  expect(L.door_f1).toBe('CLOSED');
  engine['closeLiftDoors'](L);
  expect(Object.values(L.door_state!).every((v) => v === 'CLOSED')).toBe(true);
  engine['openLiftDoor'](L, 1);
  expect(L.door_f1).toBe('OPEN');
});

test('generateTasks survives empty operational categories', () => {
  const layout = multifloorLayout();
  (layout as { locations: unknown[] }).locations = [];
  const engine = new SimEngine(layout);
  for (let i = 0; i < 300; i++) engine.step();
  expect(engine.state.robots.r1.status).not.toBe('ERROR');
});
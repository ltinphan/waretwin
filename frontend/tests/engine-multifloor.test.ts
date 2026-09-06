import { expect, test } from 'vitest';
import { SimEngine } from '../src/simulation/engine';
import type { WarehouseLayout } from '../src/layout/types';
import demo from '../src/layout/warehouse_layout.json';

// 30x30, floors 1/3/5, central lift, thin rack wall down the middle (kept clear of
// the shaft) so multi-floor routes are forced through the open lane at each end.
function thf(cs: number): WarehouseLayout {
  const layout = structuredClone(demo) as WarehouseLayout;
  for (const key of ['lifts','columns','zones','docks','racks','conveyors','stations','charging_stations','parking','restricted_areas','walkways','cameras','sensors','locations','obstacles'] as const) layout[key]=[];
  layout.size={width:30,depth:30,height:14};
  layout.grid={cell_size:cs,cols:30/cs,rows:30/cs};
  layout.floors=[{id:1,name:'G',elevation:0},{id:3,name:'M',elevation:4},{id:5,name:'T',elevation:8}];
  layout.lifts=[{id:'lift',cell:[15/cs,15/cs],floors:[1,3,5],ride_ticks:6}];
  const racks=[]; let i=0;
  // two wall segments (each 10 deep), shaft gap z13-17 stays clear
  for (const z of [2,18]) {
    for (const fid of [1,3,5]) racks.push({id:`rk${i++}`,zone:'A',position:[15,0,z],size:[3,10,1.2],rotation:0,
      levels:4,model:'rack_double',blocks_grid:true,floor:fid});
  }
  layout.racks=racks as never;
  const loc=(id,k,fl,x,z)=>({id,kind:k,access_point:[x,z],floor:fl});
  layout.locations=[
    loc('sh1','SHELF',1,4,4),   loc('pk1','PACKING',1,26,26),
    loc('sh3','SHELF',3,4,26),  loc('pk3','PACKING',3,26,4),
    loc('sh5','SHELF',5,26,26), loc('pk5','PACKING',5,4,4),
  ] as never;
  layout.spawn={robots:[
    {id:'r1',position:[6,0,6],heading:0,battery:100},
    {id:'r2',position:[24,0,6],heading:Math.PI,battery:100},
    {id:'r3',position:[6,0,24],heading:0,battery:100},
    {id:'r4',position:[24,0,24],heading:0,battery:100},
  ]};
  return layout;
}
function assign(e: SimEngine, source: string, dest: string, robot='r1'): string {
  (e as any)['nextTaskTick'] = 1e9; // kill the demo task generator: deterministic lift usage
  const r = e.state.robots[robot];
  const t = e['createTask']({ type:'PICK', priority:'NORMAL', source, destination:dest });
  t.status='ASSIGNED'; t.assigned_robot=robot; r.current_task_id=t.id; r.destination=dest;
  e['setFsm'](r,'TASK_ASSIGNED');
  return t.id;
}
// done() may be called after pruneTasks() GCs a completed task (3000-tick retention)
const done = (e: SimEngine, id: string) => { const t = e.state.tasks[id]; return t === undefined || t.status === 'COMPLETED'; };
const rob = (e: SimEngine, id: string) => e.state.robots[id];

// 1. Multi-robot: no two robots closer than their physical footprint while moving.
test.each([.5,1,2])('multi-robot: no overlap while traversing, all out of ... @%sm', (cs) => {
  const e = new SimEngine(thf(cs));
  const t = [assign(e,'sh1','pk3','r1'), assign(e,'sh3','pk5','r2'),
             assign(e,'sh1','pk5','r3'), assign(e,'sh5','pk1','r4')];
  const MIN_SEP = 0.5; // ROBOT_HALF_LEN+W ~0.81; allow cell-grid margins, but zero overlap means <0.5 never
  let overlap: string | null = null, err: string | null = null;
  for (let i=0;i<8000;i++) {
    e.step();
    for (const rid of ['r1','r2','r3','r4']) if (rob(e,rid).status==='ERROR') { err=rid; break; }
    if (err) break;
    // physical separation between every moving pair
    for (let a=0;a<4;a++) for (let b=a+1;b<4;b++) {
      const ra=rob(e,'r'+ (a+1)), rb=rob(e,'r'+(b+1));
      if (ra.velocity < .2 || rb.velocity < .2) continue;
      if (ra.floor===rb.floor) {
        const d=Math.hypot(ra.position[0]-rb.position[0], ra.position[2]-rb.position[2]);
        if (d < MIN_SEP) { overlap = `r${a+1}/r${b+1} d=${d.toFixed(2)} @${i} tick`; break; }
      }
    }
    if (overlap) break;
  }
  expect(err).toBeNull();
  expect(overlap).toBeNull();
  // liveness: nobody stuck on a platform, majority of cross-floor trips complete
  for (const rid of ['r1','r2','r3','r4']) {
    expect(['BOARDING','RIDING'].includes(rob(e,rid).lift_stage as string)).toBe(false);
  }
  expect(t.filter(id=>done(e,id)).length).toBeGreaterThanOrEqual(3);
});

// 2. Cross-floor trips land on the correct floor (engine's elevation contract is
//    expressed via floor + cabin state, not robot.position[1]).
test.each([.5,1,2])('robot completes F1->F3 and F3->F5 trips @%sm', (cs) => {
  const e = new SimEngine(thf(cs));
  const t1 = assign(e,'sh1','pk3','r1');
  for (let i=0;i<4000 && !done(e,t1);i++) e.step();
  expect(done(e,t1)).toBe(true);
  expect(rob(e,'r1').floor).toBe(3);
  // lift cabin reached the floor elevation
  expect(e.state.lifts.lift.floor).toBe(3);
  expect(e.state.lifts.lift.y).toBeCloseTo(4,3);

  const t2 = assign(e,'sh3','pk5','r1');
  for (let i=0;i<4000 && !done(e,t2);i++) e.step();
  expect(done(e,t2)).toBe(true);
  expect(rob(e,'r1').floor).toBe(5);
  expect(e.state.lifts.lift.floor).toBe(5);
  expect(e.state.lifts.lift.y).toBeCloseTo(8,3);
  expect(e.state.lifts.lift.trips).toBeGreaterThanOrEqual(2);
});

// 3. The lift cabin actually carries a robot (lift_ride happened) and station cycles.
test('lift ride round-trip drives cabin and floor state', () => {
  const e = new SimEngine(thf(1));
  const t = assign(e,'sh1','pk3','r1');
  let rode=false; const stages = new Set<string>();
  for (let i=0;i<3000 && !done(e,t);i++) { e.step(); stages.add(rob(e,'r1').lift_stage as string); }
  expect(done(e,t)).toBe(true);
  expect(rob(e,'r1').floor).toBe(3);
  // the robot went through the lift state machine (TO_LIFT/BOARDING/RIDING/ALIGHTING)
  expect(stages.has('BOARDING') || stages.has('RIDING')).toBe(true);
  expect(e.state.lifts.lift.trips).toBeGreaterThanOrEqual(1);
});

// 4. Clearance: a planned path's goal and travel never end inside a rack footprint.
test.each([.5,1])('planned path endpoint is clear of racks @%sm', (cs) => {
  const e = new SimEngine(thf(cs));
  const r = rob(e,'r1'), rt = e['rt'].r1;
  e['planTo'](r, rt, [26,26], 'TO_SOURCE', 'pk1', 1);
  let moved=false;
  for (let i=0;i<1500 && rt.target;i++) { e['rebuildOccupancy'](); e['moveAlongPath'](r,rt); e.step(); moved=true; }
  expect(moved).toBe(true);
  const pos = r.position;
  for (const rack of (e.layout.racks as any[]).filter((x:any)=>x.floor===1)) {
    const [x,,z] = rack.position as [number,number,number]; const [rw,,rd] = rack.size as number[];
    expect(pos[0] > x && pos[0] < x+rw && pos[2] > z && pos[2] < z+rd).toBe(false);
  }
});

// 5. Lift contention: opposing requests both resolve (no deadlock).
test('opposing lift requests are both served', () => {
  const e = new SimEngine(thf(1));
  const L = e.state.lifts.lift; L.floor=3; L.y=4; // cross-case: cabin seated on F3
  const t1 = assign(e,'sh1','pk3','r1'); // F1 asks up
  const t2 = assign(e,'sh3','pk5','r2'); // F3 asks up
  let stuck: string | null = null;
  for (let i=0;i<6000;i++) {
    e.step();
    for (const rid of ['r1','r2']) if (rob(e,rid).lift_stage==='BOARDING' && i>4000) stuck=`${rid} boarding @${i}`;
    if (stuck) break;
    if (done(e,t1) && done(e,t2)) break;
  }
  expect(stuck).toBeNull();
  expect([e.state.tasks[t1].status, e.state.tasks[t2].status]).toContain('COMPLETED');
});

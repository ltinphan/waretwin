import { expect, test } from 'vitest';
import { SimEngine } from '../src/simulation/engine';
import { cellCenter, nearestWalkable, toCell } from '../src/simulation/astar';
import type { WarehouseLayout } from '../src/layout/types';
import demo from '../src/layout/warehouse_layout.json';

function layoutAt(cs: number): WarehouseLayout {
  const layout=structuredClone(demo) as WarehouseLayout;
  for (const key of ['lifts','columns','zones','docks','racks','conveyors','stations','charging_stations','parking','restricted_areas','walkways','cameras','sensors','locations','obstacles'] as const) layout[key]=[];
  layout.size={width:24,depth:24,height:10};
  layout.grid={cell_size:cs,cols:24/cs,rows:24/cs};
  layout.floors=[{id:1,name:'Ground',elevation:0}];
  layout.spawn={robots:[{id:'r',position:[3.2,0,3.2],heading:0,battery:100}]};
  return layout;
}

test.each([.5,1,2])('physical movement at %sm grid resolution',cs=>{
  const engine=new SimEngine(layoutAt(cs));
  const robot=engine.state.robots.r;
  const start=cellCenter(toCell(3.2,3.2,cs),cs), goal=cellCenter(toCell(15.2,3.2,cs),cs);
  expect(robot.position).toEqual([start[0],0,start[1]]);
  expect(nearestWalkable(engine.grid,15.2,3.2)).toEqual(toCell(15.2,3.2,cs));
  // Exercise the routing/movement loop without the unrelated demo task generator.
  const rt=engine['rt'].r;
  engine['planTo'](robot,rt,[15.2,3.2],'TO_SOURCE');
  expect(rt.target).toEqual(toCell(15.2,3.2,cs));
  expect(robot.path.length).toBeGreaterThan(0);
  for(let i=0;i<1200 && rt.target;i++) {
    engine['rebuildOccupancy'](); engine['moveAlongPath'](robot,rt);
    expect(robot.position.every(Number.isFinite)).toBe(true);
  }
  expect(Math.hypot(robot.position[0]-goal[0],robot.position[2]-goal[1])).toBeLessThan(.08);
  expect(Math.abs(robot.stats.distance_m-(goal[0]-start[0]))).toBeLessThan(.1);
});

test.each([.5,1,2])('lift dimensions and congestion stay in metres at %sm',cs=>{
  const layout=layoutAt(cs);
  layout.floors.push({id:2,name:'Upper',elevation:5}); layout.spawn.robots[0].floor=2;
  layout.lifts=[{id:'lift',cell:[12/cs,12/cs],floors:[1,2],ride_ticks:10}];
  layout.zones=[{id:'z',name:'Z',color:'#ffffff',polygon:[[4,4],[8,4],[8,8],[4,8]]}];
  const e=new SimEngine(layout), lift=layout.lifts[0], cabin=e['liftCabin'](lift);
  expect(e.state.robots.r.position[1]).toBe(5);
  expect(cabin).toEqual([12+cs/2,12+cs/2]);
  expect(e['liftSlot'](lift,0)).toEqual([cabin[0]-4,cabin[1]]);
  e['blockedZones'].add('z');
  const inside=toCell(5,5,cs), outside=toCell(9,9,cs);
  expect(e['blockedCells']('r',1).has(inside.join(','))).toBe(true);
  expect(e['blockedCells']('r',1).has(outside.join(','))).toBe(false);
  e['congestedZones'].set('z',{level:1,until:100});
  expect(e['zoneSpeedFactor'](inside,1)).toBeCloseTo(.3);
  expect(e['zoneSpeedFactor'](outside,1)).toBe(1);
});

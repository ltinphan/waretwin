import { describe, expect, test } from 'vitest';
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { buildNavGrid } from '../src/layout/navgrid';
import type { WarehouseLayout } from '../src/layout/types';
import demo from '../src/layout/warehouse_layout.json';

function empty(cs=1): WarehouseLayout {
  return { ...structuredClone(demo), size: { width: 12, depth: 12, height: 10 },
    grid: {cell_size:cs,cols:Math.ceil(12/cs),rows:Math.ceil(12/cs)},
    floors:[{id:1,name:'Ground',elevation:0}], lifts:[],columns:[],zones:[],docks:[],
    racks:[],conveyors:[],stations:[],charging_stations:[],parking:[],restricted_areas:[],
    walkways:[],cameras:[],sensors:[],locations:[],obstacles:[],spawn:{robots:[]} } as WarehouseLayout;
}
const at=(layout: WarehouseLayout,x:number,z:number,floor=1) => {
  const g=buildNavGrid(layout,floor); return g.cells[z*g.cols+x];
};

describe('physical navigation geometry',()=>{
  test('concave floors block their notch on both ground and upper levels',()=>{
    const l=empty();
    l.floors[0].footprint=[[0,0],[12,0],[12,4],[4,4],[4,12],[0,12]];
    expect(at(l,8,8)).toBe(1); expect(at(l,2,8)).toBe(0);
    l.floors.push({...l.floors[0],id:2,elevation:5});
    expect(at(l,8,8,2)).toBe(1); expect(at(l,2,8,2)).toBe(0);
  });
  test('rotation changes blocked cells around the rack anchor',()=>{
    const l=empty(); l.racks=[{id:'r',position:[5,0,5],size:[4,2,1],rotation:90,blocks_grid:true} as WarehouseLayout['racks'][0]];
    expect(at(l,4,7)).toBe(1); expect(at(l,7,5)).toBe(0);
  });
  test('walkways cannot reopen absent floor and nonrobot walkways block',()=>{
    const l=empty(); l.floors[0].footprint=[[0,0],[4,0],[4,4],[0,4]];
    l.walkways=[{id:'w',polygon:[[0,0],[12,0],[12,12],[0,12]],robots_allowed:true,speed_limit_mps:1}];
    expect(at(l,8,8)).toBe(1); expect(at(l,2,2)).toBe(2);
    l.walkways[0].robots_allowed=false; expect(at(l,2,2)).toBe(1);
  });
  test('lift positions scale with cell size and affect only served floors',()=>{
    const l=empty(.5); l.floors.push({id:2,name:'Upper',elevation:5},{id:3,name:'Top',elevation:8});
    l.lifts=[{id:'lift',cell:[8,8],floors:[1,2],ride_ticks:10}];
    expect(at(l,8,8)).toBe(1); expect(at(l,16,16)).toBe(0); expect(at(l,8,8,3)).toBe(0);
  });
  test('partial edge cells and unknown floors are not navigable',()=>{
    const l=empty(); l.size.width=11.5;
    expect(at(l,11,5)).toBe(1); expect(at(l,10,5)).toBe(0);
    expect(at(l,2,2,99)).toBe(1);
  });
  test('Python and TypeScript produce identical masks',()=>{
    const cases: {layout:WarehouseLayout;floor:number}[]=[{layout:demo as WarehouseLayout,floor:1},{layout:demo as WarehouseLayout,floor:2}];
    for (const cs of [.5,1,2]) for (const rotation of [0,30,45,90,180,270]) {
      const l=empty(cs);
      l.floors[0].footprint=[[0,0],[12,0],[12,8],[8,8],[8,12],[0,12]];
      l.racks=[{id:'r',position:[5,0,5],size:[3,2,1],rotation,blocks_grid:true} as WarehouseLayout['racks'][0]];
      l.conveyors=[{id:'belt',path:[[1,1],[4,3]],width:.6,blocks_grid:true} as WarehouseLayout['conveyors'][0]];
      cases.push({layout:l,floor:1});
    }
    const partial=empty(.5); partial.size.width=11.7;
    cases.push({layout:partial,floor:1},{layout:partial,floor:99});
    const upper=empty(); upper.floors.push({id:2,name:'Upper',elevation:5});
    cases.push({layout:upper,floor:2});
    const backend=resolve('../backend'), venv=['.venv/bin/python','.venv311/bin/python'].map((r)=>resolve(backend,r)).find((c)=>existsSync(c));
    const python=process.env.PYTHON ?? (venv?venv:'python3');
    const result=spawnSync(python,['-m','tests.navgrid_bridge'],{cwd:backend,input:JSON.stringify(cases),encoding:'utf8',timeout:30000});
    expect(result.status,result.stderr).toBe(0);
    const masks=JSON.parse(result.stdout);
    cases.forEach((c,i)=>expect(Array.from(buildNavGrid(c.layout,c.floor).cells),`case ${i}`).toEqual(masks[i]));
  },30000);
});

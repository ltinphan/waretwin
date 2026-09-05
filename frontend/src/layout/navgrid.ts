import clipping, { type Polygon, type MultiPolygon } from 'polygon-clipping';
import type { P2, WarehouseLayout } from './types';

const rectangle = (x0: number, z0: number, x1: number, z1: number): Polygon =>
  [[[x0,z0], [x1,z0], [x1,z1], [x0,z1]]];
const area = (polygons: MultiPolygon) => polygons.reduce((total, polygon) => total + polygon.reduce((sum, ring, index) => {
  const signed = ring.reduce((a, p, i) => { const q = ring[(i+1)%ring.length]; return a+p[0]*q[1]-q[0]*p[1]; }, 0);
  return sum+(index ? -1 : 1)*Math.abs(signed)/2;
}, 0), 0);

/** Physical rasterization mirrored by backend/app/sim/navgrid.py. */
export function buildNavGrid(layout: WarehouseLayout, floor = 1) {
  const { cols, rows, cell_size: cs } = layout.grid;
  const cells = new Uint8Array(cols*rows), epsilon = cs*cs*1e-9;
  const onFloor = (item: { id: string; floor?: number }) => (item.floor ?? 1) === floor;
  const paint = (shape: Polygon, value: number, rectangular = false) => {
    const xs = shape[0].map(p => p[0]), zs = shape[0].map(p => p[1]);
    for (let r = Math.max(0,Math.floor(Math.min(...zs)/cs)); r < Math.min(rows,Math.ceil(Math.max(...zs)/cs)); r++) {
      for (let c = Math.max(0,Math.floor(Math.min(...xs)/cs)); c < Math.min(cols,Math.ceil(Math.max(...xs)/cs)); c++) {
        if (rectangular || area(clipping.intersection(shape, rectangle(c*cs,r*cs,(c+1)*cs,(r+1)*cs))) > epsilon) cells[r*cols+c] = value;
      }
    }
  };
  const rect = (x0: number,z0: number,x1: number,z1: number) => paint(rectangle(x0,z0,x1,z1),1,true);
  for (const w of layout.walkways ?? []) if (onFloor(w)) paint([w.polygon], (w.robots_allowed ?? true) ? 2 : 1);
  for (const rack of layout.racks ?? []) if ((rack.blocks_grid ?? true) && onFloor(rack)) {
    const [x,,z] = rack.position, [w,,d] = rack.size, angle = (rack.rotation ?? 0)*Math.PI/180;
    const points: P2[] = [[0,0],[w,0],[w,d],[0,d]];
    paint([points.map(([dx,dz]) => [x+dx*Math.cos(angle)-dz*Math.sin(angle), z+dx*Math.sin(angle)+dz*Math.cos(angle)])],1,angle===0);
  }
  for (const conveyor of layout.conveyors ?? []) if ((conveyor.blocks_grid ?? true) && onFloor(conveyor)) {
    for (let i=1; i<conveyor.path.length; i++) {
      const [ax,az]=conveyor.path[i-1], [bx,bz]=conveyor.path[i], length=Math.hypot(bx-ax,bz-az);
      if (!length) continue;
      const ux=(bx-ax)/length, uz=(bz-az)/length, h=conveyor.width/2;
      paint([[[ax-ux*h-uz*h,az-uz*h+ux*h],[bx+ux*h-uz*h,bz+uz*h+ux*h],
        [bx+ux*h+uz*h,bz+uz*h-ux*h],[ax-ux*h+uz*h,az-uz*h-ux*h]]],1);
    }
  }
  for (const item of layout.restricted_areas ?? []) if (onFloor(item) && !item.robots_allowed) rect(...item.rect);
  for (const item of [...(layout.stations ?? []), ...(layout.obstacles ?? [])]) if (onFloor(item)) rect(...item.rect);
  if (floor===1) for (const [x,z] of layout.columns ?? []) rect(x-.45,z-.45,x+.45,z+.45);
  for (const item of layout.charging_stations ?? []) if (onFloor(item)) {
    const [x,,z]=item.position; rect(x-.45,z-.4,x+.45,z+.5);
  }
  for (const lift of layout.lifts ?? []) if (lift.floors.includes(floor)) {
    const x=(lift.cell[0]+.5)*cs, z=(lift.cell[1]+.5)*cs; rect(x-1.4,z-1.9,x+1.4,z+1.9);
  }
  const building=rectangle(0,0,layout.size.width,layout.size.depth), level=layout.floors.find(f=>f.id===floor);
  if (!level) cells.fill(1);
  else {
    const boundary=level.footprint ? clipping.intersection(building,[level.footprint]) : null;
    for (let r=0;r<rows;r++) for (let c=0;c<cols;c++) {
      let inside=(c+1)*cs<=layout.size.width && (r+1)*cs<=layout.size.depth;
      if (inside && boundary) inside=area(clipping.difference(rectangle(c*cs,r*cs,(c+1)*cs,(r+1)*cs),boundary))<=epsilon;
      if (!inside) cells[r*cols+c]=1;
    }
  }
  return {cols,rows,cells,cellSize:cs};
}

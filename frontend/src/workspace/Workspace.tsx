import { useEffect, useMemo, useRef, useState } from 'react';
import { ClipboardCheck, Copy, Download, LogOut, Play, Plus, Redo2, Save, Trash2, Undo2, ZoomIn, ZoomOut } from 'lucide-react';
import type { LayoutRack, WarehouseLayout } from '../layout/types';
import { setLayout } from '../state/store';
import { workspaceClient, type LayoutRevision, type LayoutValidation, type Warehouse } from '../services/workspace';
import './workspace.css';

type History = { past: WarehouseLayout[]; present: WarehouseLayout; future: WarehouseLayout[] };
const clone = <T,>(value: T): T => structuredClone(value);

export function Workspace() {
  const [access, setAccess] = useState('');
  const [token, setToken] = useState('');
  const api = useMemo(() => workspaceClient(token), [token]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [revision, setRevision] = useState<LayoutRevision | null>(null);
  const [revisions, setRevisions] = useState<Omit<LayoutRevision, 'document' | 'warehouse_id'>[]>([]);
  const [history, setHistory] = useState<History | null>(null);
  const [selection, setSelection] = useState<string | null>(null);
  const [floor, setFloor] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [snap, setSnap] = useState(0.5);
  const [error, setError] = useState('');
  const [validation, setValidation] = useState<LayoutValidation | null>(null);
  const [busy, setBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState('New warehouse');
  const [dimensions, setDimensions] = useState({ width: 60, depth: 40, height: 10 });
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ id: string; x: number; z: number; before: WarehouseLayout } | null>(null);
  const layout = history?.present;
  const dirty = !!layout && JSON.stringify(layout) !== JSON.stringify(revision?.document);
  const readOnly = revision?.state === 'published';
  const rack = layout?.racks.find(item => item.id === selection);

  async function action(fn: () => Promise<void>) {
    setBusy(true); setError('');
    try { await fn(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  }

  function load(next: LayoutRevision) {
    setValidation(null);
    setRevision(next); setHistory({ past: [], present: clone(next.document), future: [] });
    setSelection(null); setFloor(next.document.floors[0]?.id ?? 1); setZoom(1);
  }

  function edit(fn: (draft: WarehouseLayout) => void) {
    if (readOnly || busy) return;
    setHistory(current => {
      if (!current) return current;
      const next = clone(current.present); fn(next);
      return { past: [...current.past.slice(-49), current.present], present: next, future: [] };
    });
  }

  useEffect(() => {
    const leave = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); };
    window.addEventListener('beforeunload', leave);
    return () => window.removeEventListener('beforeunload', leave);
  }, [dirty]);

  async function openWarehouse(id: string) {
    if (dirty && !window.confirm('Discard unsaved changes?')) return;
    await action(async () => {
      const rows = await api.revisions(id); setRevisions(rows);
      const preferred = rows.find(row => row.state === 'draft') ?? rows[0];
      if (preferred) load(await api.revision(id, preferred.id));
    });
  }

  function changeRack(key: 'x' | 'z' | 'width' | 'depth' | 'height' | 'rotation', value: number) {
    if (!Number.isFinite(value)) return;
    edit(draft => {
      const item = draft.racks.find(r => r.id === selection); if (!item) return;
      if (key === 'x') item.position[0] = value;
      else if (key === 'z') item.position[2] = value;
      else if (key === 'rotation') item.rotation = value;
      else item.size[key === 'width' ? 0 : key === 'height' ? 1 : 2] = Math.max(0.1, value);
    });
  }

  function pointer(event: React.PointerEvent) {
    const matrix = svg.current?.getScreenCTM();
    if (!matrix) return null;
    return new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
  }

  function endDrag(cancel = false) {
    const active = drag.current; if (!active) return;
    setHistory(current => !current ? current : cancel
      ? { ...current, present: active.before }
      : { past: [...current.past.slice(-49), active.before], present: current.present, future: [] });
    drag.current = null;
  }

  function exportLayout() {
    if (!layout) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(layout, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${layout.id}.json`; anchor.click();
    URL.revokeObjectURL(url);
  }

  if (!token) return <main className="wt-workspace wt-login">
    <form onSubmit={event => { event.preventDefault(); void action(async () => {
      const client = workspaceClient(access); await client.me(); setWarehouses(await client.warehouses());
      setToken(access); setAccess('');
    }); }}>
      <h1>WareTwin</h1><h2>Customer workspace</h2>
      <label>Workspace access token<input type="password" autoComplete="off" value={access} onChange={e => setAccess(e.target.value)} required /></label>
      {error && <p role="alert">{error}</p>}
      <button disabled={busy || !access} type="submit">Sign in</button>
      <a href="/">Open demo</a>
    </form>
  </main>;

  return <main className="wt-workspace">
    <header className="wt-header"><h1>WareTwin <span>Layouts</span></h1><a href="/">Demo</a>
      <button title="Sign out" aria-label="Sign out" onClick={() => {
        if (dirty && !window.confirm('Discard unsaved changes?')) return;
        setToken(''); setRevision(null); setHistory(null); setWarehouses([]); setRevisions([]);
      }}><LogOut size={18} /></button>
    </header>
    {error && <div className="wt-error" role="alert">{error}</div>}
    <div className="wt-toolbar">
      <select aria-label="Warehouse" disabled={busy} value={revision?.warehouse_id ?? ''} onChange={e => void openWarehouse(e.target.value)}>
        <option value="" disabled>Select warehouse</option>{warehouses.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
      </select>
      <button title="New warehouse" aria-label="New warehouse" disabled={busy} onClick={() => setCreateOpen(true)}><Plus size={18} /></button>
      {revision && <select aria-label="Revision" disabled={busy} value={revision.id} onChange={e => {
        const id = e.target.value;
        if (dirty && !window.confirm('Discard unsaved changes?')) return;
        void action(async () => load(await api.revision(revision.warehouse_id, id)));
      }}>{revisions.map(r => <option key={r.id} value={r.id}>{r.state} {r.id.slice(0, 6)} · v{r.version}</option>)}</select>}
      <span className="wt-grow" />
      <span role="status">{dirty ? 'Unsaved changes' : revision ? 'Saved' : ''}</span>
      <button title="Undo" aria-label="Undo" disabled={busy || readOnly || !history?.past.length} onClick={() => setHistory(h => !h?.past.length ? h : ({ past: h.past.slice(0, -1), present: h.past[h.past.length-1], future: [h.present, ...h.future] }))}><Undo2 size={18} /></button>
      <button title="Redo" aria-label="Redo" disabled={busy || readOnly || !history?.future.length} onClick={() => setHistory(h => !h?.future.length ? h : ({ past: [...h.past, h.present], present: h.future[0], future: h.future.slice(1) }))}><Redo2 size={18} /></button>
      <button title="Save draft" aria-label="Save draft" disabled={busy || readOnly || !dirty} onClick={() => void action(async () => {
        if (!revision || !layout) return;
        const saved = await api.save(revision, layout); setRevision(saved);
        setRevisions(await api.revisions(saved.warehouse_id));
      })}><Save size={18} /></button>
      <button title="Create alternative draft" aria-label="Create alternative draft" disabled={busy || dirty || !revision} onClick={() => void action(async () => {
        if (!revision) return;
        const alternative = await api.fork(revision); setRevisions(await api.revisions(alternative.warehouse_id)); load(alternative);
      })}><Copy size={18} /></button>
      <button title="Check saved geometry" aria-label="Check saved geometry" disabled={busy || dirty || !revision} onClick={() => void action(async () => {
        if (revision) setValidation(await api.validate(revision));
      })}><ClipboardCheck size={18} /></button>
      <button title="Export layout JSON" aria-label="Export layout JSON" disabled={!layout} onClick={exportLayout}><Download size={18} /></button>
      <button title="Open the published layout in the live demo simulation" aria-label="Open published layout in demo"
        disabled={busy || revision?.state !== 'published'}
        onClick={() => void action(async () => {
          setLayout(revision!.document);
          location.href = "/";
        })}><Play size={18} /></button>
    </div>
    {validation && !dirty && validation.version === revision?.version && <section className="wt-validation" aria-label="Geometry validation">
      <h2>{validation.valid ? 'Geometry checks passed' : `${validation.issues.length} geometry issues`}</h2>
      {validation.issues.length > 0 && <ul>{validation.issues.map((issue, index) => <li key={`${issue.path}-${index}`}>
        <strong>{issue.path}</strong>: {issue.message}
      </li>)}</ul>}
    </section>}
    {createOpen && <div className="wt-modal" role="dialog" aria-modal="true" aria-label="New warehouse"><form onSubmit={e => { e.preventDefault();
      if (dirty && !window.confirm('Discard unsaved changes?')) return;
      void action(async () => {
        const created = await api.createEmpty(name, dimensions.width, dimensions.depth, dimensions.height);
        setWarehouses(await api.warehouses()); setRevisions(await api.revisions(created.warehouse_id)); load(created); setCreateOpen(false);
      });
    }}><h2>New warehouse</h2><label>Name<input value={name} onChange={e => setName(e.target.value)} required maxLength={160} /></label>
      {(['width','depth','height'] as const).map(key => <label key={key}>{key} (m)<input type="number" min="1" max="1000" step="0.1" value={dimensions[key]} onChange={e => setDimensions(d => ({ ...d, [key]: e.target.valueAsNumber }))} required /></label>)}
      <div className="wt-actions"><button type="button" disabled={busy} onClick={() => setCreateOpen(false)}>Cancel</button><button disabled={busy}>Create warehouse</button></div>
    </form></div>}
    {!layout ? <div className="wt-empty"><h2>Your warehouses</h2><button onClick={() => setCreateOpen(true)}><Plus size={18} /> New warehouse</button></div> : <div className="wt-editor">
      <aside className="wt-properties"><h2>Building</h2>
        {(['width','depth','height'] as const).map(key => <label key={key}>{key} (m)<input type="number" min="1" max="1000" step="0.1" disabled={busy || readOnly} value={layout.size[key]} onChange={e => {
          const value = e.target.valueAsNumber; if (!Number.isFinite(value) || value <= 0 || value > 1000) return;
          edit(d => { d.size[key] = value; d.grid.cols = Math.ceil(d.size.width / d.grid.cell_size); d.grid.rows = Math.ceil(d.size.depth / d.grid.cell_size); });
        }} /></label>)}
        <label>Floor<select value={floor} onChange={e => { setFloor(Number(e.target.value)); setSelection(null); }}>{layout.floors.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}</select></label>
        <label>Snap (m)<select value={snap} onChange={e => setSnap(Number(e.target.value))}><option value={0.1}>0.1</option><option value={0.5}>0.5</option><option value={1}>1</option></select></label>
        <h2>Racks</h2><button disabled={busy || readOnly} onClick={() => { const id = crypto.randomUUID(); edit(d => d.racks.push({ id, zone: '', floor, position: [2,d.floors.find(f => f.id === floor)?.elevation ?? 0,2], size: [4,3,1.2], rotation: 0, levels: 3, model: 'standard', blocks_grid: true })); setSelection(id); }}><Plus size={18} /> Add rack</button>
        <div className="wt-object-list">{layout.racks.filter(r => (r.floor ?? 1) === floor).map((r, index) => <button key={r.id} aria-pressed={r.id === selection} onClick={() => setSelection(r.id)}>Rack {index+1} <small>{r.id.slice(0,6)}</small></button>)}</div>
      </aside>
      <section className="wt-plan-area" aria-label="Floor plan"><div className="wt-plan-tools"><span>{layout.size.width} × {layout.size.depth} m</span><button title="Zoom out" aria-label="Zoom out" onClick={() => setZoom(z => Math.max(0.5,z/1.25))}><ZoomOut size={18} /></button><button title="Zoom in" aria-label="Zoom in" onClick={() => setZoom(z => Math.min(4,z*1.25))}><ZoomIn size={18} /></button></div>
        <div className="wt-plan-scroll"><svg ref={svg} role="img" aria-label={`${layout.name} floor plan`} viewBox={`-2 -2 ${layout.size.width+4} ${layout.size.depth+4}`} style={{ width: `${zoom*100}%`, minWidth: 300 }} onPointerMove={e => {
          const active = drag.current; const point = pointer(e); if (!active || !point) return;
          setHistory(h => { if (!h) return h; const next = clone(h.present); const item = next.racks.find(r => r.id === active.id); if (item) { item.position[0] = Math.round((point.x-active.x)/snap)*snap; item.position[2] = Math.round((point.y-active.z)/snap)*snap; } return { ...h, present: next }; });
        }} onPointerUp={() => endDrag()} onPointerCancel={() => endDrag(true)}>
          <defs><pattern id="wt-grid" width={1} height={1} patternUnits="userSpaceOnUse"><path d="M 1 0 L 0 0 0 1" fill="none" stroke="#dbe3e9" strokeWidth={0.025} /></pattern></defs>
          <rect width={layout.size.width} height={layout.size.depth} fill="url(#wt-grid)" stroke="#677e89" strokeWidth={0.15} />
          {layout.floors.find(f => f.id === floor)?.footprint && <polygon points={layout.floors.find(f => f.id === floor)!.footprint!.map(p => p.join(',')).join(' ')} fill="#edf4f680" stroke="#456775" strokeWidth={0.15} />}
          {layout.racks.filter(r => (r.floor ?? 1) === floor).map(r => <rect key={r.id} x={r.position[0]} y={r.position[2]} width={r.size[0]} height={r.size[2]} transform={`rotate(${r.rotation} ${r.position[0]} ${r.position[2]})`} fill={selection === r.id ? '#19a18c' : '#78a3b2'} stroke={selection === r.id ? '#00634f' : '#365c6b'} strokeWidth={0.12} onPointerDown={e => {
            setSelection(r.id); if (readOnly || busy) return;
            const point = pointer(e); if (!point) return;
            e.currentTarget.setPointerCapture(e.pointerId); drag.current = { id: r.id, x: point.x-r.position[0], z: point.y-r.position[2], before: clone(layout) };
          }}><title>{r.id}</title></rect>)}
        </svg></div>
      </section>
      <aside className="wt-properties"><h2>Selection</h2>{rack ? <>
        <small>{rack.id}</small>
        {([['x',rack.position[0]],['z',rack.position[2]],['width',rack.size[0]],['depth',rack.size[2]],['height',rack.size[1]],['rotation',rack.rotation]] as [Parameters<typeof changeRack>[0],number][]).map(([key,value]) => <label key={key}>{key}{key === 'rotation' ? ' (°)' : ' (m)'}<input type="number" step={key === 'rotation' ? 15 : 0.1} value={value} disabled={busy || readOnly} onChange={e => changeRack(key,e.target.valueAsNumber)} /></label>)}
        <div className="wt-actions"><button title="Duplicate rack" aria-label="Duplicate rack" disabled={busy || readOnly} onClick={() => { const copy: LayoutRack = clone(rack); copy.id = crypto.randomUUID(); copy.position[0] += snap; copy.position[2] += snap; edit(d => d.racks.push(copy)); setSelection(copy.id); }}><Copy size={18} /></button>
          <button title="Delete rack" aria-label="Delete rack" disabled={busy || readOnly} onClick={() => { edit(d => { d.racks = d.racks.filter(r => r.id !== selection); }); setSelection(null); }}><Trash2 size={18} /></button></div>
      </> : <p>No selection</p>}</aside>
    </div>}
  </main>;
}

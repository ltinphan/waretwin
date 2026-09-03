/**
 * ROI Calculator Drawer — translates live simulation KPIs into dollar-value
 * projections for CxO pitch presentations.
 *
 * Fetches industry defaults from /api/roi/defaults, posts overrides + live KPI
 * to /api/roi, displays annual savings / payback / 3-year ROI.
 */
import { useEffect, useState } from "react";
import { useFocusTrap } from "../ui/useFocusTrap";
import { useStore } from "../../state/store";
import { API_URL } from "../../services/ws";

interface RoiResult {
  params: Record<string, number | string>;
  annual_throughput: number;
  annual_labor_savings: number;
  annual_error_savings: number;
  annual_energy_cost: number;
  annual_maintenance: number;
  total_investment: number;
  annual_net_savings: number;
  payback_months: number | null;
  three_year_roi_pct: number;
  fte_reduced: number;
  on_time_improvement_pct: number;
}

type Industry = "ecommerce" | "manufacturing" | "3pl";

const INDUSTRY_LABELS: Record<Industry, string> = {
  ecommerce: "E-commerce Fulfillment",
  manufacturing: "Manufacturing",
  "3pl": "3PL / Logistics",
};

export function RoiDrawer() {
  const open = useStore((s) => s.drawer === "roi");
  const setDrawer = useStore((s) => s.setDrawer);
  const kpi = useStore((s) => s.twin.kpi);
  const source = useStore((s) => s.source);
  const trap = useFocusTrap<HTMLElement>(open);
  const [industry, setIndustry] = useState<Industry>("ecommerce");
  const [defaults, setDefaults] = useState<Record<string, Record<string, number>> | null>(null);
  const [overrides, setOverrides] = useState<Record<string, number>>({});
  const [numRobots, setNumRobots] = useState(20);
  const [result, setResult] = useState<RoiResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [targetTput, setTargetTput] = useState(10);
  const [maxRobots, setMaxRobots] = useState(40);
  const [sizing, setSizing] = useState(false);
  const [sizingErr, setSizingErr] = useState<string | null>(null);
  const [sizingResult, setSizingResult] = useState<{ recommended: number; target_throughput: number; results: Array<{ num_robots: number; throughput_per_min: number; utilization: number; on_time_rate: number; avg_wait_s: number }> } | null>(null);

  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(null);
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, setDrawer]);

  useEffect(() => {
    if (!open || defaults) return;
    fetch(`${API_URL}/api/roi/defaults`).then(r => r.json()).then(setDefaults).catch(() => {});
  }, [open, defaults]);

  // when industry changes, reset overrides to that industry's defaults
  useEffect(() => {
    if (!defaults || !defaults[industry]) return;
    setOverrides({});
  }, [industry, defaults]);

  if (!open) return null;

  const d = defaults?.[industry] ?? {};
  const val = (key: string) => overrides[key] ?? d[key] ?? 0;

  const calc = async () => {
    setLoading(true); setErr(null);
    try {
      const body: Record<string, unknown> = { industry, num_robots: numRobots, ...overrides };
      const res = await fetch(`${API_URL}/api/roi`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setErr(source === "online" ? String(e) : "Backend required for ROI calculation");
    } finally { setLoading(false); }
  };

  const runSizing = async () => {
    setSizing(true); setSizingErr(null);
    try {
      const res = await fetch(`${API_URL}/api/fleet-sizing`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_throughput: targetTput, max_robots: maxRobots, duration_ticks: 600 }),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      setSizingResult(await res.json());
    } catch (e) {
      setSizingErr(source === "online" ? String(e) : "Backend required for fleet sizing");
    } finally { setSizing(false); }
  };


function exportProposal(result: RoiResult, industry: Industry, kpi: Record<string, unknown>, numRobots: number) {
  const canvas = document.querySelector("canvas");
  const screenshot = canvas?.toDataURL("image/png") ?? "";
  const now = new Date().toLocaleString();
  const w = window.open("", "_blank");
  if (!w) return;
  const rows = [
    ["Annual Throughput", `${result.annual_throughput.toLocaleString()} picks/yr`],
    ["Labor Savings", fmtMoney(result.annual_labor_savings) + "/yr"],
    ["Error Reduction Savings", fmtMoney(result.annual_error_savings) + "/yr"],
    ["Energy Cost", fmtMoney(result.annual_energy_cost) + "/yr"],
    ["Maintenance", fmtMoney(result.annual_maintenance) + "/yr"],
    ["Total Investment (CAPEX)", fmtMoney(result.total_investment)],
    ["Net Annual Savings", fmtMoney(result.annual_net_savings) + "/yr"],
    ["Payback Period", result.payback_months ? `${result.payback_months} months` : "—"],
    ["3-Year ROI", `${result.three_year_roi_pct}%`],
    ["FTE Reduced", `${result.fte_reduced} positions`],
    ["On-time Improvement", `${result.on_time_improvement_pct > 0 ? "+" : ""}${result.on_time_improvement_pct}%`],
  ];
  const op = kpi.operation as Record<string, number> | undefined;
  const fleet = kpi.fleet as Record<string, number> | undefined;
  const liveKpiRows = op ? [
    ["Throughput", `${op.throughput_per_min?.toFixed(1) ?? "—"} picks/min`],
    ["On-time Rate", `${Math.round((op.on_time_rate ?? 0) * 100)}%`],
    ["Utilization", `${Math.round((op.avg_utilization ?? 0) * 100)}%`],
    ["Completed Tasks", String(op.completed_today ?? 0)],
    ["Fleet Active", `${fleet?.active ?? 0} / ${fleet?.total ?? numRobots}`],
  ] : [];
  w.document.write(`<!DOCTYPE html><html><head><title>WareTwin Proposal — ${INDUSTRY_LABELS[industry]}</title>
<style>
  @page { margin: 2cm; }
  body { font-family: Inter, system-ui, sans-serif; color: #1a1a1a; max-width: 800px; margin: 0 auto; }
  .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid #2563eb; padding-bottom: 12px; margin-bottom: 24px; }
  .header h1 { margin: 0; font-size: 28px; }
  .header .sub { color: #666; font-size: 14px; }
  .header .brand { font-weight: 700; }
  .header .brand .accent { color: #2563eb; }
  .section { margin-bottom: 24px; }
  .section h2 { font-size: 18px; border-bottom: 1px solid #ddd; padding-bottom: 6px; margin-bottom: 12px; }
  table { width: 100%; border-collapse: collapse; }
  td { padding: 6px 8px; border-bottom: 1px solid #eee; }
  td:first-child { color: #555; }
  td:last-child { font-weight: 600; text-align: right; }
  .highlight { background: #eff6ff; }
  .screenshot { width: 100%; border: 1px solid #ddd; border-radius: 8px; margin: 12px 0; }
  .footer { margin-top: 32px; padding-top: 12px; border-top: 1px solid #ddd; color: #888; font-size: 12px; text-align: center; }
  @media print { .no-print { display: none; } }
</style></head><body>
<div class="header">
  <div><h1>AMR Implementation Proposal</h1><div class="sub">${INDUSTRY_LABELS[industry]} · ${numRobots} robots</div></div>
  <div class="brand"><span class="accent">Ware</span>Twin<br><span class="sub">Powered by Next Robotics</span></div>
</div>
${screenshot ? `<div class="section"><h2>Live Simulation Snapshot</h2><img class="screenshot" src="${screenshot}" /></div>` : ""}
<div class="section"><h2>Live KPI Summary</h2><table>${liveKpiRows.map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`).join("")}</table></div>
<div class="section"><h2>ROI Projection</h2><table>${rows.map(r => `<tr class="${["Net Annual Savings","Payback Period","3-Year ROI","Labor Savings"].includes(r[0]) ? "highlight" : ""}"><td>${r[0]}</td><td>${r[1]}</td></tr>`).join("")}</table></div>
<div class="footer">Generated by WareTwin · ${now}<br>Next Robotics — tinrobotics.com</div>
<button class="no-print" onclick="window.print()" style="position:fixed;bottom:20px;right:20px;padding:10px 20px;background:#2563eb;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px;">Print / Save PDF</button>
</body></html>`);
  w.document.close();
  setTimeout(() => w.print(), 500);
}

  const fmtMoney = (v: number) => v >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `$${(v / 1e3).toFixed(0)}K` : `$${v.toFixed(0)}`;
  const num = (v: string) => { const n = parseFloat(v); return isNaN(n) ? undefined : n; };

  return (
    <aside className="drawer wide" role="dialog" aria-label="ROI Calculator" ref={trap} tabIndex={-1}>
      <header className="drawer-h"><span>ROI Calculator</span><button className="icon-btn" aria-label="Close" onClick={() => setDrawer(null)}>✕</button></header>
      <div className="drawer-b">
        <p className="hint">Projects annual savings, payback period, and 3-year ROI from the live simulation KPIs and your cost parameters. Adjust assumptions to match the customer's operations.</p>

        <h4 className="drawer-sub" style={{ marginTop: 0 }}>Industry Profile</h4>
        <select value={industry} onChange={(e) => setIndustry(e.target.value as Industry)} style={{ width: "100%", marginBottom: 12 }}>
          {(Object.keys(INDUSTRY_LABELS) as Industry[]).map(k => <option key={k} value={k}>{INDUSTRY_LABELS[k]}</option>)}
        </select>

        <h4 className="drawer-sub">Cost Parameters</h4>
        <div className="roi-grid">
          <label>Labor rate ($/hr)<input type="number" value={val("labor_rate_hr")} onChange={e => setOverrides(o => ({ ...o, labor_rate_hr: num(e.target.value) ?? o.labor_rate_hr }))} /></label>
          <label>Shifts/day<input type="number" value={val("shifts_per_day")} onChange={e => setOverrides(o => ({ ...o, shifts_per_day: num(e.target.value) ?? o.shifts_per_day }))} /></label>
          <label>Hours/shift<input type="number" value={val("hours_per_shift")} onChange={e => setOverrides(o => ({ ...o, hours_per_shift: num(e.target.value) ?? o.hours_per_shift }))} /></label>
          <label>Working days/yr<input type="number" value={val("working_days_yr")} onChange={e => setOverrides(o => ({ ...o, working_days_yr: num(e.target.value) ?? o.working_days_yr }))} /></label>
          <label>Robot unit cost ($)<input type="number" value={val("robot_unit_cost")} onChange={e => setOverrides(o => ({ ...o, robot_unit_cost: num(e.target.value) ?? o.robot_unit_cost }))} /></label>
          <label>Maintenance ($/robot/yr)<input type="number" value={val("robot_maintenance_yr")} onChange={e => setOverrides(o => ({ ...o, robot_maintenance_yr: num(e.target.value) ?? o.robot_maintenance_yr }))} /></label>
          <label>Energy ($/kWh)<input type="number" step="0.01" value={val("energy_cost_kwh")} onChange={e => setOverrides(o => ({ ...o, energy_cost_kwh: num(e.target.value) ?? o.energy_cost_kwh }))} /></label>
          <label>Current FTE headcount<input type="number" value={val("current_fte")} onChange={e => setOverrides(o => ({ ...o, current_fte: num(e.target.value) ?? o.current_fte }))} /></label>
          <label>Fleet size (robots)<input type="number" value={numRobots} onChange={e => setNumRobots(parseInt(e.target.value) || 20)} /></label>
        </div>

        <div className="wi-ctl" style={{ marginTop: 12 }}>
          <button className="btn primary" disabled={loading || source !== "online"} onClick={calc}>
            {loading ? "Calculating…" : "Calculate ROI"}
          </button>
          {source !== "online" && <span className="hint" style={{ marginLeft: 8 }}>Backend required</span>}
        </div>
        {err && <div className="form-err" style={{ marginTop: 6 }}>⚠ {err}</div>}

        {result && (
          <>
            <h4 className="drawer-sub">Results</h4>
            <div className="kpi-grid">
              <Tile k="Annual Throughput" v={result.annual_throughput.toLocaleString()} u="picks/yr" />
              <Tile k="Labor Savings" v={fmtMoney(result.annual_labor_savings)} u="/yr" highlight />
              <Tile k="Error Reduction" v={fmtMoney(result.annual_error_savings)} u="/yr" />
              <Tile k="Energy Cost" v={fmtMoney(result.annual_energy_cost)} u="/yr" />
              <Tile k="Maintenance" v={fmtMoney(result.annual_maintenance)} u="/yr" />
              <Tile k="Total Investment" v={fmtMoney(result.total_investment)} u="CAPEX" />
              <Tile k="Net Annual Savings" v={fmtMoney(result.annual_net_savings)} u="/yr" highlight />
              <Tile k="Payback Period" v={result.payback_months ? `${result.payback_months} mo` : "—"} highlight />
              <Tile k="3-Year ROI" v={`${result.three_year_roi_pct}%`} highlight />
              <Tile k="FTE Reduced" v={String(result.fte_reduced)} u="positions" />
              <Tile k="On-time Improvement" v={`${result.on_time_improvement_pct > 0 ? "+" : ""}${result.on_time_improvement_pct}%`} />
            </div>
            <div className="wi-actions">
              <button className="btn" onClick={() => { setResult(null); setOverrides({}); }}>Reset</button>
              <button className="btn primary" onClick={() => result && exportProposal(result, industry, kpi as unknown as Record<string, unknown>, numRobots)}>📄 Export Proposal</button>
            </div>
          </>
        )}

        <h4 className="drawer-sub" style={{ marginTop: 24 }}>Fleet Sizing Wizard</h4>
        <p className="hint">Set a target throughput — the wizard runs simulations with different fleet sizes and recommends the minimum robot count that meets your target.</p>
        <div className="wi-ctl" style={{ marginTop: 8 }}>
          <label>Target throughput (picks/min)
            <input type="number" value={targetTput} min={1} max={50} onChange={e => setTargetTput(parseInt(e.target.value) || 10)} style={{ width: 80 }} />
          </label>
          <label>Max robots to test
            <input type="number" value={maxRobots} min={10} max={80} onChange={e => setMaxRobots(parseInt(e.target.value) || 40)} style={{ width: 60 }} />
          </label>
          <button className="btn primary" disabled={sizing || source !== "online"} onClick={runSizing}>
            {sizing ? "Simulating…" : "Run Analysis"}
          </button>
        </div>
        {sizingErr && <div className="form-err" style={{ marginTop: 6 }}>⚠ {sizingErr}</div>}
        {sizingResult && (
          <>
            <div className="bubble" style={{ maxWidth: "100%", background: "var(--panel-2)", border: "1px solid var(--accent)", marginTop: 8 }}>
              <b>Recommended: {sizingResult.recommended} robots</b> to reach {sizingResult.target_throughput} picks/min
            </div>
            <table className="dt wi-table" style={{ marginTop: 8 }}>
              <thead><tr><th>Robots</th><th>Throughput</th><th>Utilization</th><th>On-time</th><th>Wait (s)</th></tr></thead>
              <tbody>
                {sizingResult.results.map((r) => (
                  <tr key={r.num_robots} className={r.num_robots === sizingResult.recommended ? "sel" : ""}>
                    <td>{r.num_robots}{r.num_robots === sizingResult.recommended && " ✓"}</td>
                    <td>{r.throughput_per_min.toFixed(1)}/min</td>
                    <td>{Math.round(r.utilization * 100)}%</td>
                    <td>{Math.round(r.on_time_rate * 100)}%</td>
                    <td>{r.avg_wait_s.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button className="btn" onClick={() => setSizingResult(null)} style={{ marginTop: 6 }}>Clear</button>
          </>
        )}
      </div>
    </aside>
  );
}

function Tile({ k, v, u, highlight }: { k: string; v: string; u?: string; highlight?: boolean }) {
  return <div className={"tile" + (highlight ? " highlight" : "")}><div className="k">{k}</div><div className="v">{v}{u && <span className="u"> {u}</span>}</div></div>;
}
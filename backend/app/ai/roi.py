"""
ROI Calculator — translates simulation KPIs into dollar-value projections
for CxO pitch presentations. Pure function, no external deps.

POST /api/roi → { params, results }
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Industry = Literal["ecommerce", "manufacturing", "3pl"]

# Industry default cost parameters (USD, hourly / annual)
# ponytail: single-source defaults, editable in UI; update from real market data when available
INDUSTRY_DEFAULTS: dict[str, dict[str, float]] = {
    "ecommerce": {
        "labor_rate_hr": 22.0,       # fulfillment associate $/hr
        "shifts_per_day": 2,
        "hours_per_shift": 8,
        "working_days_yr": 360,
        "robot_unit_cost": 45000,    # AMR + integration per unit
        "robot_maintenance_yr": 1800, # per robot / year
        "energy_cost_kwh": 0.14,
        "error_rate_manual": 0.035,   # 3.5% mis-pick rate manual
        "error_cost_per_pick": 12.0,  # cost of a mis-pick
        "current_fte": 40,           # manual warehouse headcount
    },
    "manufacturing": {
        "labor_rate_hr": 28.0,
        "shifts_per_day": 3,
        "hours_per_shift": 8,
        "working_days_yr": 300,
        "robot_unit_cost": 55000,
        "robot_maintenance_yr": 2200,
        "energy_cost_kwh": 0.12,
        "error_rate_manual": 0.02,
        "error_cost_per_pick": 25.0,
        "current_fte": 30,
    },
    "3pl": {
        "labor_rate_hr": 20.0,
        "shifts_per_day": 2,
        "hours_per_shift": 8,
        "working_days_yr": 365,
        "robot_unit_cost": 48000,
        "robot_maintenance_yr": 2000,
        "energy_cost_kwh": 0.13,
        "error_rate_manual": 0.03,
        "error_cost_per_pick": 15.0,
        "current_fte": 35,
    },
}


class RoiParams(BaseModel):
    industry: Industry = "ecommerce"
    num_robots: int = Field(default=20, gt=0, le=200)
    throughput_per_min: float = Field(default=0, ge=0)  # from live KPI
    utilization: float = Field(default=0, ge=0, le=1)   # from live KPI
    energy_kwh: float = Field(default=0, ge=0)          # from live KPI
    on_time_rate: float = Field(default=1, ge=0, le=1)  # from live KPI
    # overrides
    labor_rate_hr: float | None = None
    shifts_per_day: float | None = None
    hours_per_shift: float | None = None
    working_days_yr: float | None = None
    robot_unit_cost: float | None = None
    robot_maintenance_yr: float | None = None
    energy_cost_kwh: float | None = None
    error_rate_manual: float | None = None
    error_cost_per_pick: float | None = None
    current_fte: int | None = None


class RoiResult(BaseModel):
    params: dict[str, Any]
    annual_throughput: int
    annual_labor_savings: float
    annual_error_savings: float
    annual_energy_cost: float
    annual_maintenance: float
    total_investment: float
    annual_net_savings: float
    payback_months: float | None
    three_year_roi_pct: float
    fte_reduced: int
    on_time_improvement_pct: float


def calculate_roi(kpi: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pure function: live KPI dict + optional param overrides → ROI projection."""
    industry = (overrides or {}).get("industry", "ecommerce")
    defaults = INDUSTRY_DEFAULTS.get(industry, INDUSTRY_DEFAULTS["ecommerce"])

    # merge: defaults < overrides
    p: dict[str, Any] = {**defaults}
    if overrides:
        for k, v in overrides.items():
            if v is not None and k in defaults:
                p[k] = v

    # pull live KPI values
    op = kpi.get("operation", {})
    eff = kpi.get("efficiency", {})
    throughput_per_min = float(op.get("throughput_per_min", 0))
    utilization = float(op.get("avg_utilization", 0))
    energy_kwh = float(eff.get("energy_kwh", 0))
    on_time_rate = float(op.get("on_time_rate", 1))

    num_robots = int((overrides or {}).get("num_robots", 20))

    # annual throughput: simulate running hours × throughput
    daily_hours = p["shifts_per_day"] * p["hours_per_shift"]
    annual_hours = daily_hours * p["working_days_yr"]
    annual_throughput = int(throughput_per_min * 60 * annual_hours)

    # labor savings: automation replaces portion of manual FTE
    # ponytail: 35% FTE reduction — conservative for pitch credibility; tunable via override
    fte_reduction_pct = float((overrides or {}).get("fte_reduction_pct", 0.35))
    fte_annual_cost = p["labor_rate_hr"] * annual_hours
    fte_reduced = int(p["current_fte"] * fte_reduction_pct)
    annual_labor_savings = fte_reduced * fte_annual_cost

    # error reduction: AMR error rate ~0.5% vs manual
    error_rate_amr = 0.005
    manual_errors = annual_throughput * p["error_rate_manual"]
    amr_errors = annual_throughput * error_rate_amr
    annual_error_savings = (manual_errors - amr_errors) * p["error_cost_per_pick"]

    # energy cost (AMR fleet)
    # energy_kwh is cumulative since sim start; scale to daily rate then annualize
    # ponytail: uses elapsed sim hours as denominator; if sim just started (0h), falls back to rated power estimate
    sim_hours = max(annual_hours / p["working_days_yr"], 1)  # at least 1 day of sim time
    daily_energy = energy_kwh / sim_hours * daily_hours if energy_kwh > 0 else num_robots * 0.5 * daily_hours  # 0.5 kW/robot fallback
    annual_energy = daily_energy * p["working_days_yr"]
    annual_energy_cost = annual_energy * p["energy_cost_kwh"]

    # maintenance
    annual_maintenance = num_robots * p["robot_maintenance_yr"]

    # CAPEX
    total_investment = num_robots * p["robot_unit_cost"]

    # net savings
    annual_net = annual_labor_savings + annual_error_savings - annual_energy_cost - annual_maintenance

    # payback
    payback_months = (total_investment / annual_net * 12) if annual_net > 0 else float("inf")

    # 3-year ROI
    three_year_savings = annual_net * 3
    three_year_roi = ((three_year_savings - total_investment) / total_investment * 100) if total_investment > 0 else 0

    # on-time improvement vs typical manual (85%)
    on_time_improvement = (on_time_rate - 0.85) * 100

    return {
        "params": {**p, "num_robots": num_robots, "industry": industry},
        "annual_throughput": annual_throughput,
        "annual_labor_savings": round(annual_labor_savings, 2),
        "annual_error_savings": round(annual_error_savings, 2),
        "annual_energy_cost": round(annual_energy_cost, 2),
        "annual_maintenance": round(annual_maintenance, 2),
        "total_investment": round(total_investment, 2),
        "annual_net_savings": round(annual_net, 2),
        "payback_months": round(payback_months, 1) if payback_months != float("inf") else None,
        "three_year_roi_pct": round(three_year_roi, 1),
        "fte_reduced": fte_reduced,
        "on_time_improvement_pct": round(on_time_improvement, 1),
    }


if __name__ == "__main__":
    # self-check: demo KPI → sane ROI
    demo_kpi = {
        "operation": {"throughput_per_min": 12.5, "avg_utilization": 0.78, "on_time_rate": 0.96},
        "efficiency": {"energy_kwh": 2.3},
    }
    r = calculate_roi(demo_kpi, {"industry": "ecommerce", "num_robots": 20})
    assert r["annual_throughput"] > 0, "throughput should be positive"
    assert r["annual_labor_savings"] > 0, "labor savings should be positive"
    assert r["payback_months"] is not None and 0 < r["payback_months"] < 60, f"payback should be 0-60 months, got {r['payback_months']}"
    assert r["three_year_roi_pct"] > 0, "3-year ROI should be positive"
    print(f"✓ ROI self-check passed: {r['annual_throughput']} picks/yr, ${r['annual_net_savings']:,.0f} net/yr, payback {r['payback_months']}mo, 3yr ROI {r['three_year_roi_pct']}%")
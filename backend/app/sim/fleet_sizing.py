"""
Fleet Sizing Wizard — runs multiple what-if clones with different fleet sizes
to find the optimal robot count for a target throughput.

POST /api/fleet-sizing → { target_throughput, results: [{num_robots, throughput, utilization, ...}], recommended }
"""
from __future__ import annotations

import asyncio
from typing import Any

from .engine import SimEngine
from .whatif import _window_kpi


def _run_with_fleet(engine: SimEngine, num_robots: int, duration: int) -> dict[str, Any]:
    """Clone engine, set fleet size, run, return KPIs. Reuses whatif infrastructure."""
    clone = engine.clone()
    S = clone.state

    # Disable robots beyond num_robots by setting them OFFLINE
    robot_ids = list(S["robots"].keys())
    for i, rid in enumerate(robot_ids):
        if i >= num_robots:
            r = S["robots"][rid]
            r["status"] = "OFFLINE"
            r["fsm"] = "OFFLINE"
            # cancel any assigned task
            if r.get("current_task_id"):
                tid = r["current_task_id"]
                if tid in S["tasks"]:
                    t = S["tasks"][tid]
                    t["status"] = "WAITING"
                    t["assigned_robot"] = None
                r["current_task_id"] = None

    start_tick = S["sim"]["tick"]
    start_completed = clone.completed_count
    start_wait = sum(r["stats"]["wait_ticks"] for r in S["robots"].values())
    start_energy = sum(r["stats"]["energy_wh"] for r in S["robots"].values())
    counts: dict[str, int] = {}

    for _ in range(duration):
        clone.step()
        for e in clone.new_events:
            counts[e["type"]] = counts.get(e["type"], 0) + 1
        clone.new_events = []

    kpi = _window_kpi(clone, start_tick, start_completed, start_wait, start_energy, duration, counts)
    return {
        "num_robots": num_robots,
        "throughput_per_min": kpi["throughput_per_min"],
        "utilization": kpi["utilization"],
        "on_time_rate": kpi["on_time_rate"],
        "avg_wait_s": kpi["avg_wait_s"],
        "congestion_index": kpi["congestion_index"],
        "energy_kwh": kpi["energy_kwh"],
        "completed": kpi["completed"],
    }


def run_fleet_sizing(engine: SimEngine, target_throughput: float, max_robots: int = 40, duration_ticks: int = 600) -> dict[str, Any]:
    """
    Run simulations with fleet sizes from 5 to max_robots (step 5),
    return throughput curve + recommended count for target.

    ponytail: step=5 keeps compute fast (~7 runs × 600 ticks); use step=1 for fine-grained if needed
    """
    sizes = list(range(5, max_robots + 1, 5))
    results = []
    for n in sizes:
        r = _run_with_fleet(engine, n, duration_ticks)
        results.append(r)

    # find smallest fleet that meets target throughput
    recommended = None
    for r in results:
        if r["throughput_per_min"] >= target_throughput:
            recommended = r["num_robots"]
            break

    # if none meet target, recommend the one with highest throughput
    if recommended is None and results:
        recommended = max(results, key=lambda r: r["throughput_per_min"])["num_robots"]

    return {
        "target_throughput": target_throughput,
        "duration_ticks": duration_ticks,
        "results": results,
        "recommended": recommended,
    }


if __name__ == "__main__":
    # self-check: can't run without full engine, just test the function signature
    assert callable(run_fleet_sizing)
    assert callable(_run_with_fleet)
    print("✓ Fleet sizing module imports OK")
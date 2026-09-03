"""Tests for ROI and fleet-sizing API endpoints."""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_roi_defaults():
    r = client.get("/api/roi/defaults")
    assert r.status_code == 200
    d = r.json()
    assert "ecommerce" in d
    assert "manufacturing" in d
    assert "3pl" in d
    assert d["ecommerce"]["labor_rate_hr"] > 0


def test_roi_calculation():
    r = client.post("/api/roi", json={"industry": "ecommerce", "num_robots": 20})
    assert r.status_code == 200
    result = r.json()
    assert result["annual_throughput"] >= 0
    assert result["total_investment"] > 0
    assert "payback_months" in result  # may be None if net savings <= 0
    assert "three_year_roi_pct" in result


def test_roi_bad_industry():
    r = client.post("/api/roi", json={"industry": "nonexistent", "num_robots": 20})
    assert r.status_code == 200  # falls back to ecommerce defaults


def test_fleet_sizing_validation():
    # bad target
    r = client.post("/api/fleet-sizing", json={"target_throughput": -1, "max_robots": 40})
    assert r.status_code == 400
    # bad max_robots
    r = client.post("/api/fleet-sizing", json={"target_throughput": 10, "max_robots": 2})
    assert r.status_code == 400
    # non-numeric
    r = client.post("/api/fleet-sizing", json={"target_throughput": "abc"})
    assert r.status_code == 400


def test_fleet_sizing_valid():
    r = client.post("/api/fleet-sizing", json={"target_throughput": 5, "max_robots": 20, "duration_ticks": 100})
    assert r.status_code == 200
    result = r.json()
    assert "results" in result
    assert "recommended" in result
    assert len(result["results"]) > 0

"""Unit tests for messy-data contracts that hiring reviewers care about."""

from __future__ import annotations

from datetime import date

from app.analytics import (
    build_operations_dashboard,
    list_execution_backlog,
    pipeline_to_execution,
    _overdue_work_orders,
)
from app.monday_client import BoardSnapshot
from app.schema import (
    is_header_artifact,
    normalize_name,
    resolve_period,
    resolve_sectors,
    stage_bucket,
)


def test_resolve_sectors_energy_umbrella():
    available = ["Renewables", "Powerline", "Mining", "Railways"]
    matched, note = resolve_sectors("energy", available)
    assert matched == ["Renewables", "Powerline"]
    assert note and "Renewables" in note


def test_resolve_sectors_unknown_lists_options():
    matched, note = resolve_sectors("aerospace", ["Mining", "Renewables"])
    assert matched == []
    assert note and "Mining" in note


def test_resolve_period_this_quarter_fiscal_apr_mar():
    # 25 Aug 2026 → Q2 FY26-27 (Jul–Sep)
    start, end, label = resolve_period("this_quarter", today=date(2026, 8, 25))
    assert start == "2026-07-01"
    assert end == "2026-09-30"
    assert "Q2" in label and "FY26" in label


def test_resolve_period_last_fiscal_year():
    start, end, label = resolve_period("last_fiscal_year", today=date(2026, 8, 25))
    assert start == "2025-04-01"
    assert end == "2026-03-31"
    assert "FY25" in label


def test_header_artifact_detection():
    assert is_header_artifact(
        {
            "id": "1",
            "name": "Deal Name",
            "Deal Stage": "Deal Stage",
            "Sector/service": "Sector/service",
        }
    )
    assert not is_header_artifact(
        {
            "id": "2",
            "name": "Naruto",
            "Deal Stage": "B. Sales Qualified Leads",
            "Sector/service": "Mining",
        }
    )


def test_stage_bucket_won_and_open():
    assert stage_bucket("H. Work Order Received") == "won"
    assert stage_bucket("G. Project Won") == "won"
    assert stage_bucket("A. Lead Generated") == "open"
    assert stage_bucket("L. Project Lost") == "lost"


def test_join_dedups_work_orders_across_same_masked_name():
    deals = BoardSnapshot(
        board_id="d",
        board_name="Deals",
        records=[
            {"id": "1", "name": "Sakura", "Deal Stage": "H. Work Order Received", "Sector/service": "Mining"},
            {"id": "2", "name": "Sakura", "Deal Stage": "G. Project Won", "Sector/service": "Mining"},
        ],
        fetched_at=0.0,
    )
    work_orders = BoardSnapshot(
        board_id="w",
        board_name="Work Orders",
        records=[
            {"id": "wo1", "name": "Sakura", "Execution Status": "Completed", "Sector": "Mining"},
            {"id": "wo2", "name": "Sakura", "Execution Status": "Ongoing", "Sector": "Mining"},
        ],
        fetched_at=0.0,
    )
    result = pipeline_to_execution(deals, work_orders)
    assert result["won_deals"] == 2
    assert result["won_deals_with_work_orders"] == 2
    # Without dedup this would double-count to 4.
    assert result["distinct_work_orders_behind_won_deals"] == 2
    assert sum(result["execution_status_of_won_deals"].values()) == 2


def test_normalize_name_collapses_punctuation():
    assert normalize_name("Sakura!") == normalize_name("sakura")
    assert normalize_name("Scooby-Doo") == "scooby doo"


def test_overdue_and_backlog_pagination():
    today = date(2026, 8, 25)
    records = [
        {
            "id": "1",
            "name": "A",
            "Execution Status": "Ongoing",
            "Probable End Date": "2026-01-01",
            "Sector": "Mining",
        },
        {
            "id": "2",
            "name": "B",
            "Execution Status": "Completed",
            "Probable End Date": "2026-01-01",
            "Sector": "Mining",
        },
        {
            "id": "3",
            "name": "C",
            "Execution Status": "Not Started",
            "Probable End Date": "2026-12-01",
            "Sector": "Mining",
        },
        {
            "id": "4",
            "name": "D",
            "Execution Status": "Pause / struck",
            "Probable End Date": "2025-06-01",
            "Sector": "Renewables",
        },
    ]
    overdue = _overdue_work_orders(records, today=today)
    assert {r["id"] for r in overdue} == {"1", "4"}

    snap = BoardSnapshot(
        board_id="w",
        board_name="Work Orders",
        records=records,
        fetched_at=0.0,
    )
    page1 = list_execution_backlog(snap, limit=1, offset=0, today=today)
    assert page1["total_matching"] == 2
    assert page1["returned"] == 1
    assert page1["has_more"] is True
    assert page1["next_offset"] == 1

    page2 = list_execution_backlog(snap, limit=1, offset=1, today=today)
    assert page2["returned"] == 1
    assert page2["has_more"] is False


def test_operations_dashboard_pulse_keys():
    today = date(2026, 8, 25)
    deals = BoardSnapshot(
        board_id="d",
        board_name="Deals",
        records=[
            {
                "id": "d1",
                "name": "Alpha",
                "Deal Stage": "Qualification",
                "Sector/service": "Mining",
                "Masked Deal value": "100",
            },
            {
                "id": "d2",
                "name": "Beta",
                "Deal Stage": "Project Won",
                "Sector/service": "Renewables",
                "Masked Deal value": "200",
            },
        ],
        fetched_at=0.0,
    )
    work_orders = BoardSnapshot(
        board_id="w",
        board_name="Work Orders",
        records=[
            {
                "id": "1",
                "name": "Alpha",
                "Execution Status": "Ongoing",
                "Probable End Date": "2026-01-01",
                "Sector": "Mining",
                "Amount Receivable (Masked)": "50",
            }
        ],
        fetched_at=0.0,
    )
    dash = build_operations_dashboard(deals, work_orders, today=today)
    assert dash["pulse"]["open_deals"] == 1
    assert dash["pulse"]["overdue_work_orders"] == 1
    assert dash["backlog"]["rows"]
    assert "funnel" in dash
    assert "receivables" in dash

"""Deterministic BI computations over monday.com board snapshots.

Every number the agent reports originates here. The LLM only chooses which function to
call and how to narrate the result, so it cannot invent figures.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import Any, Callable

from app.monday_client import BoardSnapshot
from app.schema import (
    DEAL_CLIENT,
    DEAL_DATE_FIELDS,
    DEAL_NAME,
    DEAL_OWNER,
    DEAL_PROBABILITY,
    DEAL_SECTOR,
    DEAL_STAGE,
    DEAL_STATUS,
    DEAL_SUMMARY_FIELDS,
    DEAL_VALUE,
    MONEY_FIELDS,
    WO_CLIENT,
    WO_COLLECTION_STATUS,
    WO_DATE_FIELDS,
    WO_INVOICE_STATUS,
    WO_NAME,
    WO_NATURE,
    WO_OWNER,
    WO_SECTOR,
    WO_SERIAL,
    WO_STATUS,
    WO_SUMMARY_FIELDS,
    WO_TYPE,
    parse_date,
    parse_number,
    normalize_name,
    resolve_period,
    resolve_sectors,
    stage_bucket,
)


def _distinct(records: list[dict[str, Any]], key: str) -> list[str]:
    return sorted({str(r.get(key)) for r in records if r.get(key)})


def _period_filter(
    records: list[dict[str, Any]],
    column: str | None,
    start: str | None,
    end: str | None,
) -> tuple[list[dict[str, Any]], int]:
    """Filter by date range. Rows with an unparseable date are excluded but counted."""
    if not column or (not start and not end):
        return records, 0

    lo = date.fromisoformat(start) if start else None
    hi = date.fromisoformat(end) if end else None
    kept: list[dict[str, Any]] = []
    undated = 0
    for record in records:
        value = parse_date(record.get(column))
        if value is None:
            undated += 1
            continue
        if lo and value < lo:
            continue
        if hi and value > hi:
            continue
        kept.append(record)
    return kept, undated


def _scope(
    snapshot: BoardSnapshot,
    sector_field: str,
    sector: str | None,
    date_fields: dict[str, str],
    date_field: str | None,
    period: str | None,
    today: date | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply sector and period filters, returning rows plus how it was interpreted."""
    records = snapshot.records
    notes: list[str] = []

    sectors, sector_note = resolve_sectors(sector, _distinct(records, sector_field))
    if sector_note:
        notes.append(sector_note)
    if sector:
        wanted = {s.lower() for s in sectors}
        records = [r for r in records if str(r.get(sector_field, "")).lower() in wanted]

    column = date_fields.get(date_field or "")
    start, end, label = resolve_period(period, today=today)
    if period and not column:
        notes.append(
            f"No date field selected, so '{period}' was ignored. Available: {', '.join(date_fields)}."
        )
        start = end = None
    before_period = records
    records, undated = _period_filter(records, column, start, end)
    if undated:
        notes.append(f"{undated} row(s) excluded from the period because their {column} is blank or unparseable.")

    scope: dict[str, Any] = {
        "sectors_included": sectors or "all",
        "period": label,
        "date_field": column or "not filtered",
        "matched_records": len(records),
    }
    if start:
        scope["date_range"] = f"{start} to {end}"
    if not records and before_period and column:
        available = [d for d in (parse_date(r.get(column)) for r in before_period) if d]
        if available:
            scope["no_rows_in_period"] = (
                f"Nothing matches this period. {column} in the data spans "
                f"{min(available).isoformat()} to {max(available).isoformat()} — report that "
                "rather than implying there is no activity."
            )
    if notes:
        scope["interpretation"] = notes
    return records, scope


def _money(records: list[dict[str, Any]], column: str) -> dict[str, Any]:
    values = [parse_number(r.get(column)) for r in records]
    known = [v for v in values if v is not None]
    return {
        "total": round(sum(known), 2),
        "records_with_value": len(known),
        "records_missing_value": len(values) - len(known),
    }


def _group(
    records: list[dict[str, Any]],
    key: Callable[[dict[str, Any]], str],
    value_column: str | None = None,
) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0})
    for record in records:
        bucket = out[key(record)]
        bucket["count"] += 1
        if value_column:
            amount = parse_number(record.get(value_column))
            if amount is not None:
                bucket["value"] = round(bucket.get("value", 0.0) + amount, 2)
                bucket["records_with_value"] = bucket.get("records_with_value", 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["count"]))


def _project(records: list[dict[str, Any]], fields: list[str], limit: int) -> list[dict[str, Any]]:
    """Return only the columns worth showing, to keep token cost predictable."""
    return [{f: r.get(f) for f in fields if r.get(f) is not None} for r in records[:limit]]


def _latest(records: list[dict[str, Any]], columns: list[str]) -> str | None:
    seen = [parse_date(r.get(c)) for r in records for c in columns]
    dates = [d for d in seen if d]
    return max(dates).isoformat() if dates else None


# --- Tool implementations ---------------------------------------------------------


def board_vocabulary(deals: BoardSnapshot, work_orders: BoardSnapshot) -> dict[str, Any]:
    """The real values on both boards, so terminology can be grounded before filtering."""
    return {
        "deals_board": {
            "records": len(deals.records),
            "sectors": dict(Counter(str(r.get(DEAL_SECTOR) or "(blank)") for r in deals.records)),
            "stages": dict(Counter(str(r.get(DEAL_STAGE) or "(blank)") for r in deals.records)),
            "statuses": dict(Counter(str(r.get(DEAL_STATUS) or "(blank)") for r in deals.records)),
            "closure_probability": dict(
                Counter(str(r.get(DEAL_PROBABILITY) or "(blank)") for r in deals.records)
            ),
            "date_fields": list(DEAL_DATE_FIELDS),
            "latest_date_in_data": _latest(deals.records, list(DEAL_DATE_FIELDS.values())),
        },
        "work_orders_board": {
            "records": len(work_orders.records),
            "sectors": dict(Counter(str(r.get(WO_SECTOR) or "(blank)") for r in work_orders.records)),
            "execution_statuses": dict(
                Counter(str(r.get(WO_STATUS) or "(blank)") for r in work_orders.records)
            ),
            "nature_of_work": dict(
                Counter(str(r.get(WO_NATURE) or "(blank)") for r in work_orders.records)
            ),
            "date_fields": list(WO_DATE_FIELDS),
            "latest_date_in_data": _latest(work_orders.records, list(WO_DATE_FIELDS.values())),
        },
        "notes": [
            "Sector names are Skylark's own. Industry terms like 'energy' map onto Renewables and Powerline.",
            "Deal values and all work-order amounts are masked, so treat them as relative signals.",
            "Closure Probability is categorical (High/Medium/Low), not a percentage.",
        ],
        "data_freshness": {
            "deals": deals.freshness(),
            "work_orders": work_orders.freshness(),
        },
    }


def deal_pipeline_summary(
    deals: BoardSnapshot,
    sector: str | None = None,
    period: str | None = None,
    date_field: str = "created",
    today: date | None = None,
) -> dict[str, Any]:
    records, scope = _scope(deals, DEAL_SECTOR, sector, DEAL_DATE_FIELDS, date_field, period, today)

    buckets = Counter(stage_bucket(r.get(DEAL_STAGE)) for r in records)
    open_deals = [r for r in records if stage_bucket(r.get(DEAL_STAGE)) == "open"]
    won_deals = [r for r in records if stage_bucket(r.get(DEAL_STAGE)) == "won"]
    decided = buckets["won"] + buckets["lost"]

    return {
        "scope": scope,
        "total_deals": len(records),
        "funnel": dict(buckets),
        "win_rate_of_decided_deals": round(buckets["won"] / decided, 3) if decided else None,
        "value_masked": {
            "all_deals": _money(records, DEAL_VALUE),
            "open_deals": _money(open_deals, DEAL_VALUE),
            "won_deals": _money(won_deals, DEAL_VALUE),
        },
        "by_stage": _group(records, lambda r: str(r.get(DEAL_STAGE) or "(blank)"), DEAL_VALUE),
        "by_sector": _group(records, lambda r: str(r.get(DEAL_SECTOR) or "(blank)"), DEAL_VALUE),
        "open_pipeline_by_probability": _group(
            open_deals, lambda r: str(r.get(DEAL_PROBABILITY) or "(blank)"), DEAL_VALUE
        ),
        "data_quality": {
            "missing_sector": sum(1 for r in records if not r.get(DEAL_SECTOR)),
            "missing_deal_value": sum(1 for r in records if parse_number(r.get(DEAL_VALUE)) is None),
            "missing_stage": sum(1 for r in records if not r.get(DEAL_STAGE)),
            "notes": [
                "Values are masked; use for comparison, not absolute reporting.",
                "'Won' covers Project Won, Work Order Received, Invoice Sent, Amount Accrued and Project Completed.",
            ],
        },
        "data_freshness": deals.freshness(),
    }


def work_order_ops_summary(
    work_orders: BoardSnapshot,
    sector: str | None = None,
    period: str | None = None,
    date_field: str = "po",
    today: date | None = None,
) -> dict[str, Any]:
    records, scope = _scope(work_orders, WO_SECTOR, sector, WO_DATE_FIELDS, date_field, period, today)
    overdue = _overdue_work_orders(records, today=today)
    order_value = MONEY_FIELDS["order_value_excl_gst"]

    return {
        "scope": scope,
        "total_work_orders": len(records),
        "by_execution_status": _group(records, lambda r: str(r.get(WO_STATUS) or "(blank)"), order_value),
        "by_sector": _group(records, lambda r: str(r.get(WO_SECTOR) or "(blank)"), order_value),
        "by_nature_of_work": _group(records, lambda r: str(r.get(WO_NATURE) or "(blank)"), order_value),
        "by_type_of_work": _group(records, lambda r: str(r.get(WO_TYPE) or "(blank)")),
        "order_value_excl_gst_masked": _money(records, order_value),
        "past_end_date_but_not_complete": {
            "count": len(overdue),
            "examples": _project(
                overdue,
                [WO_NAME, WO_SECTOR, WO_STATUS, WO_DATE_FIELDS["end"], WO_CLIENT],
                10,
            ),
            "note": (
                "This is a preview of 10. Call list_execution_backlog to retrieve the full list "
                "(paginated)."
            ),
        },
        "data_quality": {
            "missing_execution_status": sum(1 for r in records if not r.get(WO_STATUS)),
            "missing_end_date": sum(1 for r in records if parse_date(r.get(WO_DATE_FIELDS["end"])) is None),
            "notes": ["Amounts are masked. Slippage is inferred from Probable End Date, which is a plan, not a commitment."],
        },
        "data_freshness": work_orders.freshness(),
    }


_ACTIVE_EXECUTION = {
    "ongoing",
    "executed until current month",
    "partial completed",
    "not started",
    "pause / struck",
    "details pending from client",
}


def _overdue_work_orders(
    records: list[dict[str, Any]],
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Work orders past Probable End Date that are not Completed."""
    reference = today or date.today()
    overdue: list[dict[str, Any]] = []
    for record in records:
        end = parse_date(record.get(WO_DATE_FIELDS["end"]))
        status = str(record.get(WO_STATUS) or "").strip().lower()
        if not end or end >= reference:
            continue
        if status in {"completed", ""}:
            continue
        if status in _ACTIVE_EXECUTION or status:
            # Any non-completed status past end date counts as backlog/slippage.
            overdue.append(record)
    overdue.sort(key=lambda r: parse_date(r.get(WO_DATE_FIELDS["end"])) or date.min)
    return overdue


def list_execution_backlog(
    work_orders: BoardSnapshot,
    sector: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    today: date | None = None,
) -> dict[str, Any]:
    """Full list of work orders past probable end date and not completed (paginated)."""
    records, scope = _scope(work_orders, WO_SECTOR, sector, WO_DATE_FIELDS, None, None, today)
    overdue = _overdue_work_orders(records, today=today)
    if status:
        needle = status.strip().lower()
        overdue = [r for r in overdue if needle in str(r.get(WO_STATUS) or "").lower()]

    limit = max(1, min(int(limit or 100), 200))
    offset = max(0, int(offset or 0))
    page = overdue[offset : offset + limit]

    return {
        "scope": scope,
        "definition": (
            "Work orders whose Probable End Date is before today and Execution Status is not Completed."
        ),
        "total_matching": len(overdue),
        "offset": offset,
        "limit": limit,
        "returned": len(page),
        "has_more": offset + len(page) < len(overdue),
        "next_offset": offset + len(page) if offset + len(page) < len(overdue) else None,
        "by_status": dict(Counter(str(r.get(WO_STATUS) or "(blank)") for r in overdue)),
        "by_sector": dict(Counter(str(r.get(WO_SECTOR) or "(blank)") for r in overdue)),
        "records": _project(
            page,
            [
                WO_NAME,
                WO_SERIAL,
                WO_SECTOR,
                WO_STATUS,
                WO_CLIENT,
                WO_OWNER,
                WO_DATE_FIELDS["end"],
                WO_DATE_FIELDS["start"],
                MONEY_FIELDS["order_value_excl_gst"],
            ],
            limit,
        ),
        "guidance": (
            "If has_more is true, call again with next_offset to continue the list. "
            "You can list the full backlog across pages — do not claim the tool cannot return all items."
        ),
        "data_freshness": work_orders.freshness(),
    }


def build_operations_dashboard(
    deals: BoardSnapshot,
    work_orders: BoardSnapshot,
    today: date | None = None,
) -> dict[str, Any]:
    """Glanceable ops pulse for the UI — same math as agent tools, stable keys for the frontend."""
    pipeline = deal_pipeline_summary(deals, today=today)
    ops = work_order_ops_summary(work_orders, today=today)
    backlog = list_execution_backlog(work_orders, limit=12, today=today)
    cash = revenue_and_collections(work_orders, today=today)
    join = pipeline_to_execution(deals, work_orders, today=today)

    funnel = pipeline.get("funnel") or {}
    open_n = int(funnel.get("open") or 0)
    overdue_n = int(backlog.get("total_matching") or 0)
    won_no_wo = int((join.get("won_deals_without_work_orders") or {}).get("count") or 0)
    open_value = ((pipeline.get("value_masked") or {}).get("open_deals") or {}).get("total")
    receivables_total = ((cash.get("receivables") or {}).get("total_masked"))

    end_field = WO_DATE_FIELDS["end"]
    order_col = MONEY_FIELDS["order_value_excl_gst"]
    recv_col = MONEY_FIELDS["receivable"]

    overdue_by_sector = [
        {"sector": sector, "count": count}
        for sector, count in sorted(
            (backlog.get("by_sector") or {}).items(),
            key=lambda kv: -kv[1],
        )[:8]
    ]

    backlog_rows = [
        {
            "name": row.get(WO_NAME),
            "serial": row.get(WO_SERIAL),
            "sector": row.get(WO_SECTOR),
            "status": row.get(WO_STATUS),
            "client": row.get(WO_CLIENT),
            "end_date": row.get(end_field),
            "order_value_masked": row.get(order_col),
        }
        for row in (backlog.get("records") or [])
    ]

    receivable_rows = [
        {
            "name": row.get(WO_NAME),
            "client": row.get(WO_CLIENT),
            "sector": row.get(WO_SECTOR),
            "receivable_masked": row.get(recv_col),
            "collection_status": row.get(WO_COLLECTION_STATUS),
        }
        for row in ((cash.get("receivables") or {}).get("top_exposures") or [])
    ]

    funnel_order = ["open", "won", "lost", "on_hold", "disqualified", "other"]
    funnel_bars = [
        {"bucket": key, "count": int(funnel.get(key) or 0)}
        for key in funnel_order
        if int(funnel.get(key) or 0)
    ]
    for key, count in funnel.items():
        if key not in funnel_order and int(count or 0):
            funnel_bars.append({"bucket": str(key), "count": int(count)})

    return {
        "pulse": {
            "open_deals": open_n,
            "win_rate_of_decided_deals": pipeline.get("win_rate_of_decided_deals"),
            "open_pipeline_value_masked": open_value,
            "overdue_work_orders": overdue_n,
            "receivables_total_masked": receivables_total,
            "won_deals_without_work_order": won_no_wo,
            "total_deals": pipeline.get("total_deals"),
            "total_work_orders": ops.get("total_work_orders"),
        },
        "funnel": funnel_bars,
        "overdue_by_sector": overdue_by_sector,
        "backlog": {
            "total": overdue_n,
            "definition": backlog.get("definition"),
            "rows": backlog_rows,
            "has_more": overdue_n > len(backlog_rows),
        },
        "receivables": {
            "total_masked": receivables_total,
            "rows": receivable_rows,
        },
        "caveats": [
            "Amounts are masked — compare relatively, not as absolute reporting.",
            "Overdue uses Probable End Date (plan), not a contractual deadline.",
        ],
        "data_freshness": {
            "deals": deals.freshness(),
            "work_orders": work_orders.freshness(),
        },
    }


def prepare_leadership_brief(
    deals: BoardSnapshot,
    work_orders: BoardSnapshot,
    sector: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Structured leadership pack: pipeline, execution, cash, CRM gaps, suggested follow-ups."""
    pipeline = deal_pipeline_summary(deals, sector=sector, today=today)
    ops = work_order_ops_summary(work_orders, sector=sector, today=today)
    cash = revenue_and_collections(work_orders, sector=sector, today=today)
    join = pipeline_to_execution(deals, work_orders, sector=sector, today=today)
    backlog = list_execution_backlog(work_orders, sector=sector, limit=15, today=today)

    funnel = pipeline.get("funnel") or {}
    open_n = int(funnel.get("open") or 0)
    won_n = int(funnel.get("won") or 0)
    overdue_n = int(backlog.get("total_matching") or 0)
    won_no_wo = int((join.get("won_deals_without_work_orders") or {}).get("count") or 0)

    headline_bits = [
        f"{pipeline.get('total_deals', 0)} deals in scope",
        f"{open_n} open / {won_n} won",
    ]
    if overdue_n:
        headline_bits.append(f"{overdue_n} WOs past probable end date")
    if won_no_wo:
        headline_bits.append(f"{won_no_wo} won deals with no work order")

    return {
        "brief_type": "leadership_update",
        "headline": " · ".join(headline_bits),
        "pipeline_health": {
            "total_deals": pipeline.get("total_deals"),
            "funnel": funnel,
            "win_rate_of_decided_deals": pipeline.get("win_rate_of_decided_deals"),
            "open_value_masked": (pipeline.get("value_masked") or {}).get("open_deals"),
            "by_sector_top": dict(list((pipeline.get("by_sector") or {}).items())[:5]),
            "scope": pipeline.get("scope"),
        },
        "execution": {
            "total_work_orders": ops.get("total_work_orders"),
            "by_execution_status": ops.get("by_execution_status"),
            "slippage_past_end_date": overdue_n,
            "slippage_by_status": backlog.get("by_status"),
            "slippage_preview": backlog.get("records"),
        },
        "collections": {
            "totals_masked": cash.get("totals_masked"),
            "ratios": cash.get("ratios"),
            "top_receivables": (cash.get("receivables") or {}).get("top_exposures"),
        },
        "crm_consistency": {
            "won_without_work_order": join.get("won_deals_without_work_orders"),
            "work_orders_without_deal": (join.get("consistency_checks") or {}).get(
                "work_orders_with_no_matching_deal"
            ),
            "work_orders_not_marked_won": (join.get("consistency_checks") or {}).get(
                "work_orders_whose_deal_is_not_marked_won"
            ),
        },
        "data_caveats": [
            "All monetary figures are masked — use for relative comparison only.",
            "Slippage uses Probable End Date (plan), not a contractual deadline.",
            "Cross-board join is on normalised masked deal names; collisions can merge distinct deals.",
            *list(((pipeline.get("scope") or {}).get("interpretation") or [])),
        ],
        "suggested_follow_ups": [
            "List the full execution backlog with list_execution_backlog.",
            "Drill into the sector with the largest open pipeline value.",
            "Review won deals that still have no work order.",
            "Check top receivable exposures and collection status.",
        ],
        "data_freshness": {
            "deals": deals.freshness(),
            "work_orders": work_orders.freshness(),
        },
    }


def revenue_and_collections(
    work_orders: BoardSnapshot,
    sector: str | None = None,
    period: str | None = None,
    date_field: str = "invoice",
    group_by: str = "sector",
    today: date | None = None,
) -> dict[str, Any]:
    records, scope = _scope(work_orders, WO_SECTOR, sector, WO_DATE_FIELDS, date_field, period, today)

    keys: dict[str, Callable[[dict[str, Any]], str]] = {
        "sector": lambda r: str(r.get(WO_SECTOR) or "(blank)"),
        "execution_status": lambda r: str(r.get(WO_STATUS) or "(blank)"),
        "invoice_status": lambda r: str(r.get(WO_INVOICE_STATUS) or "(blank)"),
        "collection_status": lambda r: str(r.get(WO_COLLECTION_STATUS) or "(blank)"),
        "client": lambda r: str(r.get(WO_CLIENT) or "(blank)"),
        "owner": lambda r: str(r.get(WO_OWNER) or "(blank)"),
    }
    key = keys.get(group_by, keys["sector"])

    totals = {label: _money(records, column) for label, column in MONEY_FIELDS.items()}
    billed = totals["billed_excl_gst"]["total"]
    ordered = totals["order_value_excl_gst"]["total"]
    collected = totals["collected_incl_gst"]["total"]

    receivable_column = MONEY_FIELDS["receivable"]
    top_receivables = sorted(
        (r for r in records if parse_number(r.get(receivable_column))),
        key=lambda r: parse_number(r.get(receivable_column)) or 0,
        reverse=True,
    )

    return {
        "scope": scope,
        "totals_masked": totals,
        "ratios": {
            "billed_over_order_value": round(billed / ordered, 3) if ordered else None,
            "collected_over_billed_note": (
                "Collected is inclusive of GST while billed here is exclusive, so the raw ratio "
                "overstates collection. Compare trends, not the absolute figure."
            ),
            "collected_masked": collected,
        },
        f"by_{group_by}": {
            bucket: {
                "count": stats["count"],
                "order_value": stats.get("value", 0.0),
            }
            for bucket, stats in _group(records, key, MONEY_FIELDS["order_value_excl_gst"]).items()
        },
        "receivables": {
            "total_masked": totals["receivable"]["total"],
            "top_exposures": _project(
                top_receivables,
                [WO_NAME, WO_CLIENT, WO_SECTOR, receivable_column, WO_COLLECTION_STATUS],
                10,
            ),
        },
        "data_quality": {
            "notes": [
                "All amounts are masked and mix GST-inclusive and GST-exclusive columns; labels state which.",
                "Blank amount cells are excluded from totals and counted in records_missing_value.",
            ]
        },
        "data_freshness": work_orders.freshness(),
    }


def pipeline_to_execution(
    deals: BoardSnapshot,
    work_orders: BoardSnapshot,
    sector: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Join the two boards on deal name to compare what was won against what is executing."""
    deal_records, scope = _scope(deals, DEAL_SECTOR, sector, DEAL_DATE_FIELDS, None, None, today)
    wo_records, _ = _scope(work_orders, WO_SECTOR, sector, WO_DATE_FIELDS, None, None, today)

    wo_by_deal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in wo_records:
        wo_by_deal[normalize_name(record.get(WO_NAME))].append(record)

    won = [r for r in deal_records if stage_bucket(r.get(DEAL_STAGE)) == "won"]
    won_with_wo: list[dict[str, Any]] = []
    won_without_wo: list[dict[str, Any]] = []
    for record in won:
        if wo_by_deal.get(normalize_name(record.get(DEAL_NAME))):
            won_with_wo.append(record)
        else:
            won_without_wo.append(record)

    deal_keys = {normalize_name(r.get(DEAL_NAME)) for r in deal_records}
    won_keys = {normalize_name(r.get(DEAL_NAME)) for r in won}
    orphan_work = [r for r in wo_records if normalize_name(r.get(WO_NAME)) not in deal_keys]
    executing_not_won = [
        r
        for r in wo_records
        if normalize_name(r.get(WO_NAME)) in deal_keys
        and normalize_name(r.get(WO_NAME)) not in won_keys
    ]

    # A masked name can belong to several deals, so count each work order once.
    matched_orders = {
        w["id"]: w
        for r in won_with_wo
        for w in wo_by_deal[normalize_name(r.get(DEAL_NAME))]
    }
    matched_status = Counter(str(w.get(WO_STATUS) or "(blank)") for w in matched_orders.values())

    return {
        "scope": scope,
        "join_key": "deal name, normalised (lowercase, punctuation removed)",
        "won_deals": len(won),
        "won_deals_with_work_orders": len(won_with_wo),
        "distinct_work_orders_behind_won_deals": len(matched_orders),
        "won_deals_without_work_orders": {
            "count": len(won_without_wo),
            "examples": _project(won_without_wo, [DEAL_NAME, DEAL_SECTOR, DEAL_STAGE, DEAL_VALUE], 10),
        },
        "execution_status_of_won_deals": dict(matched_status),
        "consistency_checks": {
            "work_orders_with_no_matching_deal": {
                "count": len(orphan_work),
                "examples": _project(orphan_work, [WO_NAME, WO_SECTOR, WO_STATUS], 10),
            },
            "work_orders_whose_deal_is_not_marked_won": {
                "count": len(executing_not_won),
                "examples": _project(executing_not_won, [WO_NAME, WO_SECTOR, WO_STATUS], 10),
            },
        },
        "data_quality": {
            "notes": [
                "Names are masked aliases, so a name collision between two real deals would merge them.",
                "One deal can have several work orders; counts are of deals unless stated otherwise.",
                "Gaps here are usually CRM hygiene issues rather than missing revenue.",
            ]
        },
        "data_freshness": {
            "deals": deals.freshness(),
            "work_orders": work_orders.freshness(),
        },
    }


def search_deals(
    deals: BoardSnapshot,
    sector: str | None = None,
    stage: str | None = None,
    status: str | None = None,
    owner: str | None = None,
    client: str | None = None,
    outcome: str | None = None,
    period: str | None = None,
    date_field: str = "created",
    text_contains: str | None = None,
    limit: int = 25,
    today: date | None = None,
) -> dict[str, Any]:
    records, scope = _scope(deals, DEAL_SECTOR, sector, DEAL_DATE_FIELDS, date_field, period, today)
    records = _text_filters(
        records,
        {DEAL_STAGE: stage, DEAL_STATUS: status, DEAL_OWNER: owner, DEAL_CLIENT: client},
        text_contains,
    )
    if outcome:
        records = [r for r in records if stage_bucket(r.get(DEAL_STAGE)) == outcome.lower()]

    return {
        "scope": scope,
        "matches": len(records),
        "returned": min(len(records), limit),
        "records": _project(records, DEAL_SUMMARY_FIELDS, limit),
        "data_freshness": deals.freshness(),
    }


def search_work_orders(
    work_orders: BoardSnapshot,
    sector: str | None = None,
    status: str | None = None,
    owner: str | None = None,
    client: str | None = None,
    nature_of_work: str | None = None,
    period: str | None = None,
    date_field: str = "po",
    text_contains: str | None = None,
    limit: int = 25,
    today: date | None = None,
) -> dict[str, Any]:
    records, scope = _scope(work_orders, WO_SECTOR, sector, WO_DATE_FIELDS, date_field, period, today)
    records = _text_filters(
        records,
        {
            WO_STATUS: status,
            WO_OWNER: owner,
            WO_CLIENT: client,
            WO_NATURE: nature_of_work,
        },
        text_contains,
    )

    return {
        "scope": scope,
        "matches": len(records),
        "returned": min(len(records), limit),
        "records": _project(records, WO_SUMMARY_FIELDS, limit),
        "data_freshness": work_orders.freshness(),
    }


def _text_filters(
    records: list[dict[str, Any]],
    column_filters: dict[str, str | None],
    text_contains: str | None,
) -> list[dict[str, Any]]:
    for column, wanted in column_filters.items():
        if not wanted:
            continue
        needle = wanted.strip().lower()
        records = [r for r in records if needle in str(r.get(column) or "").lower()]
    if text_contains:
        needle = text_contains.strip().lower()
        records = [
            r
            for r in records
            if needle in " ".join(str(v) for v in r.values() if v is not None).lower()
        ]
    return records

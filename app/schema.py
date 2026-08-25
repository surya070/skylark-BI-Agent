"""Domain knowledge about the two monday.com boards.

Column titles, sector vocabulary, funnel-stage buckets and period parsing live here so
the analytics and agent layers stay free of magic strings.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable

# --- Deals board -----------------------------------------------------------------

DEAL_NAME = "name"
DEAL_SECTOR = "Sector/service"
DEAL_STAGE = "Deal Stage"
DEAL_STATUS = "Deal Status"
DEAL_VALUE = "Masked Deal value"
DEAL_OWNER = "Owner code"
DEAL_CLIENT = "Client Code"
DEAL_PROBABILITY = "Closure Probability"
DEAL_PRODUCT = "Product deal"

DEAL_DATE_FIELDS = {
    "created": "Created Date",
    "expected_close": "Tentative Close Date",
    "actual_close": "Close Date (A)",
}

DEAL_SUMMARY_FIELDS = [
    DEAL_NAME,
    DEAL_SECTOR,
    DEAL_STAGE,
    DEAL_STATUS,
    DEAL_VALUE,
    DEAL_PROBABILITY,
    DEAL_OWNER,
    DEAL_CLIENT,
    "Created Date",
    "Tentative Close Date",
    "Close Date (A)",
]

# --- Work Orders board -----------------------------------------------------------

WO_NAME = "name"
WO_SECTOR = "Sector"
WO_STATUS = "Execution Status"
WO_CLIENT = "Customer Name Code"
WO_SERIAL = "Serial #"
WO_NATURE = "Nature of Work"
WO_TYPE = "Type of Work"
WO_OWNER = "BD/KAM Personnel code"
WO_INVOICE_STATUS = "Invoice Status"
WO_BILLING_STATUS = "Billing Status"
WO_COLLECTION_STATUS = "Collection status"

WO_DATE_FIELDS = {
    "po": "Date of PO/LOI",
    "start": "Probable Start Date",
    "end": "Probable End Date",
    "delivery": "Data Delivery Date",
    "invoice": "Last invoice date",
    "collection": "Collection Date",
}

MONEY_FIELDS = {
    "order_value_excl_gst": "Amount in Rupees (Excl of GST) (Masked)",
    "billed_excl_gst": "Billed Value in Rupees (Excl of GST.) (Masked)",
    "collected_incl_gst": "Collected Amount in Rupees (Incl of GST.) (Masked)",
    "receivable": "Amount Receivable (Masked)",
    "to_be_billed_excl_gst": "Amount to be billed in Rs. (Exl. of GST) (Masked)",
}

WO_SUMMARY_FIELDS = [
    WO_NAME,
    WO_SERIAL,
    WO_SECTOR,
    WO_STATUS,
    WO_NATURE,
    WO_TYPE,
    WO_CLIENT,
    WO_OWNER,
    "Date of PO/LOI",
    "Probable Start Date",
    "Probable End Date",
    MONEY_FIELDS["order_value_excl_gst"],
    MONEY_FIELDS["billed_excl_gst"],
    MONEY_FIELDS["receivable"],
    WO_INVOICE_STATUS,
    WO_COLLECTION_STATUS,
]

# --- Sector vocabulary -----------------------------------------------------------
# The boards use Skylark's own sector names. Founders ask in industry language
# ("energy", "power", "infra"), which does not appear verbatim in the data.

SECTOR_ALIASES: dict[str, list[str]] = {
    "Renewables": ["renewable", "renewables", "solar", "wind", "green", "clean energy"],
    "Powerline": ["powerline", "power line", "transmission", "grid", "t&d", "distribution"],
    "Mining": ["mining", "mine", "mines", "mineral", "minerals", "coal", "quarry"],
    "Railways": ["railway", "railways", "rail", "metro", "train"],
    "Construction": ["construction", "real estate", "building"],
    "Manufacturing": ["manufacturing", "factory", "industrial", "plant"],
    "Security and Surveillance": ["security", "surveillance", "defence", "defense"],
    "Aviation": ["aviation", "airport", "airline"],
    "DSP": ["dsp", "data services", "data processing"],
    "Others": ["other", "others", "misc", "miscellaneous"],
    "Tender": ["tender", "tenders", "bid", "bids"],
}

# Umbrella terms that legitimately span several canonical sectors.
SECTOR_GROUPS: dict[str, list[str]] = {
    "energy": ["Renewables", "Powerline"],
    "power": ["Renewables", "Powerline"],
    "utilities": ["Renewables", "Powerline"],
    "infra": ["Railways", "Construction", "Powerline"],
    "infrastructure": ["Railways", "Construction", "Powerline"],
    "resources": ["Mining"],
}


def resolve_sectors(term: str | None, available: Iterable[str]) -> tuple[list[str], str | None]:
    """Map a founder's sector wording onto sector values that exist on the board.

    Returns the matched sector names plus a note explaining the interpretation, so the
    agent can tell the user how an ambiguous term like "energy" was handled.
    """
    if not term:
        return [], None

    options = sorted({str(v) for v in available if v})
    lookup = {opt.lower(): opt for opt in options}
    query = term.strip().lower()

    if query in lookup:
        return [lookup[query]], None

    if query in SECTOR_GROUPS:
        matched = [s for s in SECTOR_GROUPS[query] if s in options]
        if matched:
            note = (
                f"'{term}' is not a sector on the board. Interpreted as {', '.join(matched)}."
            )
            return matched, note

    alias_hits = [
        canonical
        for canonical, aliases in SECTOR_ALIASES.items()
        if canonical in options and any(a in query or query in a for a in aliases)
    ]
    if alias_hits:
        note = None
        if len(alias_hits) > 1 or alias_hits[0].lower() != query:
            note = f"Matched '{term}' to {', '.join(alias_hits)}."
        return alias_hits, note

    substring_hits = [opt for opt in options if query in opt.lower()]
    if substring_hits:
        return substring_hits, None

    return [], (
        f"No sector matches '{term}'. Sectors on this board: {', '.join(options)}."
    )


# --- Funnel stages ---------------------------------------------------------------
# Stages are lettered (A. Lead Generated ... O. Not Relevant at all). Bucketing is a
# judgement call: "Work Order Received" onwards is treated as won because execution
# has been authorised.

_STAGE_BUCKETS: list[tuple[str, tuple[str, ...]]] = [
    ("won", ("g.", "h.", "j.", "k.", "project completed", "project won")),
    ("lost", ("l.",)),
    ("on_hold", ("m.",)),
    ("disqualified", ("n.", "o.")),
]


def stage_bucket(stage: Any) -> str:
    s = str(stage or "").strip().lower()
    if not s:
        return "unknown"
    for bucket, prefixes in _STAGE_BUCKETS:
        if s.startswith(prefixes):
            return bucket
    return "open"


# --- Periods ---------------------------------------------------------------------
# Skylark invoices are numbered SDPL/FY25-26/..., so the fiscal year runs Apr-Mar.

FISCAL_START_MONTH = 4

PERIOD_CHOICES = [
    "all_time",
    "this_month",
    "last_month",
    "this_quarter",
    "last_quarter",
    "this_fiscal_year",
    "last_fiscal_year",
    "last_30_days",
    "last_90_days",
]


def _fiscal_year_start(d: date) -> date:
    year = d.year if d.month >= FISCAL_START_MONTH else d.year - 1
    return date(year, FISCAL_START_MONTH, 1)


def _fiscal_quarter_start(d: date) -> date:
    fy_start = _fiscal_year_start(d)
    months_in = (d.year - fy_start.year) * 12 + (d.month - fy_start.month)
    quarter_index = months_in // 3
    month = fy_start.month + quarter_index * 3
    year = fy_start.year + (month - 1) // 12
    return date(year, (month - 1) % 12 + 1, 1)


def _add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    return date(d.year + total // 12, total % 12 + 1, 1)


def fiscal_label(d: date) -> str:
    start = _fiscal_year_start(d)
    quarter = ((d.year - start.year) * 12 + (d.month - start.month)) // 3 + 1
    return f"Q{quarter} FY{str(start.year)[2:]}-{str(start.year + 1)[2:]}"


def resolve_period(
    period: str | None,
    today: date | None = None,
) -> tuple[str | None, str | None, str]:
    """Turn a period keyword into an inclusive ISO date range plus a human label."""
    today = today or date.today()
    key = (period or "all_time").strip().lower().replace(" ", "_").replace("-", "_")

    if key in {"", "all_time", "all", "any", "none"}:
        return None, None, "all time"

    if key == "this_month":
        start = today.replace(day=1)
        return start.isoformat(), (_add_months(start, 1) - timedelta(days=1)).isoformat(), start.strftime("%B %Y")

    if key == "last_month":
        start = _add_months(today.replace(day=1), -1)
        return start.isoformat(), (_add_months(start, 1) - timedelta(days=1)).isoformat(), start.strftime("%B %Y")

    if key == "this_quarter":
        start = _fiscal_quarter_start(today)
        end = _add_months(start, 3) - timedelta(days=1)
        return start.isoformat(), end.isoformat(), fiscal_label(start)

    if key == "last_quarter":
        start = _add_months(_fiscal_quarter_start(today), -3)
        end = _add_months(start, 3) - timedelta(days=1)
        return start.isoformat(), end.isoformat(), fiscal_label(start)

    if key in {"this_fiscal_year", "this_fy", "fy_to_date", "ytd"}:
        start = _fiscal_year_start(today)
        end = _add_months(start, 12) - timedelta(days=1)
        return start.isoformat(), end.isoformat(), f"FY{str(start.year)[2:]}-{str(start.year + 1)[2:]}"

    if key in {"last_fiscal_year", "last_fy"}:
        start = _add_months(_fiscal_year_start(today), -12)
        end = _add_months(start, 12) - timedelta(days=1)
        return start.isoformat(), end.isoformat(), f"FY{str(start.year)[2:]}-{str(start.year + 1)[2:]}"

    if key in {"last_30_days", "last_90_days"}:
        days = 30 if "30" in key else 90
        start = today - timedelta(days=days)
        return start.isoformat(), today.isoformat(), f"last {days} days"

    fy = re.match(r"^fy_?(\d{2,4})_?(\d{2,4})?$", key)
    if fy:
        year = int(fy.group(1))
        year += 2000 if year < 100 else 0
        start = date(year, FISCAL_START_MONTH, 1)
        end = _add_months(start, 12) - timedelta(days=1)
        return start.isoformat(), end.isoformat(), f"FY{str(year)[2:]}-{str(year + 1)[2:]}"

    q = re.match(r"^q([1-4])_?fy_?(\d{2,4})", key)
    if q:
        year = int(q.group(2))
        year += 2000 if year < 100 else 0
        start = _add_months(date(year, FISCAL_START_MONTH, 1), (int(q.group(1)) - 1) * 3)
        end = _add_months(start, 3) - timedelta(days=1)
        return start.isoformat(), end.isoformat(), fiscal_label(start)

    return None, None, f"unrecognised period '{period}' — treated as all time"


# --- Messy-data helpers ----------------------------------------------------------


def is_header_artifact(record: dict[str, Any]) -> bool:
    """Detect rows where the spreadsheet header was imported as a data row."""
    hits = 0
    for key, value in record.items():
        if key == "id" or not isinstance(value, str):
            continue
        if value.strip().lower() == str(key).strip().lower():
            hits += 1
            if hits >= 2:
                return True
    return False


def normalize_name(value: Any) -> str:
    """Canonical form of a deal name, for joining across the two boards."""
    s = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "null", "-", "n/a", "na", "#n/a"}:
        return None
    s = s.replace(",", "").replace("\u20b9", "").replace("$", "").replace("%", "")
    match = re.search(r"-?\d+(?:\.\d+)?", s)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y")


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    head = s[:10]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None

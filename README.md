# Skylark Operations Intelligence

A business intelligence agent for Skylark Drones that answers founder-level questions about the sales pipeline and project delivery, using live data from two monday.com boards.

**Live demo:** `[REPLACE_WITH_HOSTED_URL](https://skylark-bi-agent-f2gd.onrender.com)`
**Decision Log:** `DecisionLog.docx`

---

## The problem I set out to solve

Skylark's deal funnel and work order tracker live on separate monday.com boards. Answering something as ordinary as *"how is energy doing and is anything slipping?"* means filtering two boards, matching deals to work orders by hand, and doing arithmetic in a spreadsheet. The data is also genuinely messy: an imported header row sitting in the item list, blank dates, amounts masked for confidentiality, and duplicate masked deal names.

So I built two surfaces over the same computation layer:

- **A pulse dashboard** that answers the questions people ask every day, with no LLM involved.
- **A chat agent** for everything else — narrative briefs, unusual cuts, and follow-up questions.

The dashboard handles monitoring. The agent handles thinking. Both read from the same deterministic analytics functions, so they never disagree.

---

## The most important design decision

**The language model never produces a number.**

Every figure comes from a pure Python function in `app/analytics.py`. The model's only jobs are choosing which function to call, picking its arguments, and narrating the result. If a tool didn't return a figure, the system prompt requires the agent to say so rather than estimate.

This matters for a BI tool more than anything else on the feature list. A dashboard that is occasionally wrong is worse than no dashboard, and "the LLM computed it" is not an auditable answer for a founder making a resourcing call.

---

## Architecture

```
Browser (static HTML/CSS/JS)
   │
   ├── GET  /api/dashboard ──► analytics.build_operations_dashboard()   [no LLM]
   │
   └── POST /api/chat ──────► agent.BIAgent.chat()
                                  │
                                  ├── Gemini (OpenAI-compatible endpoint)
                                  │      plans → picks tool → narrates
                                  │
                                  └── 9 tools ──► app/analytics.py      [all arithmetic]
                                                        │
                                                        └── app/monday_client.py
                                                                 │
                                                            monday.com GraphQL
                                                          (120s cache, stale fallback)
```

### Modules

| File | Responsibility |
|------|----------------|
| `app/monday_client.py` | GraphQL client: cursor pagination, cell normalisation, header-row removal, 120s cache, serves a stale snapshot if monday.com is down |
| `app/schema.py` | Domain knowledge: column names, sector vocabulary, funnel-stage buckets, April–March fiscal periods, number/date parsers |
| `app/analytics.py` | Every calculation. Pure functions over board snapshots — no LLM, no I/O |
| `app/agent.py` | Tool definitions, the tool-calling loop, system constraints, model failover |
| `app/main.py` | FastAPI routes, rate limiting, startup cache warm-up |
| `static/` | Split-pane UI: dashboard left, chat right |
| `tests/` | Unit tests for the messy-data contracts |

### The agent's tools

| Tool | What it answers |
|------|-----------------|
| `get_board_vocabulary` | Which sectors, stages and statuses actually exist — used to ground terminology before filtering |
| `get_deal_pipeline_summary` | Funnel buckets, win rate, value by stage and sector, open pipeline by closure probability |
| `get_work_order_ops_summary` | Execution status mix, work type mix, order value, slippage preview |
| `list_execution_backlog` | The full paginated list of overdue work orders |
| `get_revenue_and_collections` | Order value, billed, collected, yet-to-bill, receivables, largest exposures |
| `get_pipeline_to_execution` | Cross-board join: won deals vs work orders, and CRM consistency gaps |
| `prepare_leadership_brief` | A structured leadership pack assembled from both boards in one call |
| `search_deals` / `search_work_orders` | Individual records for named or shortlist questions |

---

## Handling the messy data

These were the actual problems in the boards, and what each one required:

**An imported header row appearing as a data item.** The Work Orders sheet had its real header on row 2, so importing produced an item whose cell values equal their own column titles. `schema.is_header_artifact()` detects that pattern and the client drops the row before it reaches any calculation, reporting the count in the freshness payload rather than silently discarding it.

**Founders don't use the board's vocabulary.** "Energy" is not a sector in the data; Renewables and Powerline are. `resolve_sectors()` maps industry language onto real sector values and returns a note explaining the interpretation, which the agent is required to pass on to the user. So "how is energy doing" answers correctly *and* says which sectors it included.

**Dates are sparse and the fiscal year isn't the calendar year.** Periods resolve against an April–March fiscal year. When a period filter matches nothing, the tool returns the actual date span present in that column so the agent reports "the data ends in January 2026" instead of implying the business is idle. The agent is also instructed not to apply a period filter at all unless the user asked for one — an early version invented "this quarter" on general questions and reported zero.

**Duplicate masked deal names.** Confidentiality masking means several distinct deals can share a name, so a naive join double-counts. The cross-board join deduplicates by work order id. The join is still fuzzy by nature, and the agent says so in its caveats.

**Amounts are masked.** Every money figure is labelled masked and framed for ranking and comparison, never as publishable finance. Billed is GST-exclusive while collected is GST-inclusive, so the tool returns a note instead of a misleading ratio.

---

## Reliability

The demo runs on Gemini's free tier, which fails in predictable ways. Each one is handled rather than surfaced as a stack trace:

- **Quota, availability and capacity errors** (`429`, `403`, `404`, `503`) walk a short chain of Flash models and only report an error if all of them fail.
- **A 22-second per-attempt timeout** stops one overloaded model from freezing the UI.
- **Gemini 3.x thought signatures** are echoed back on tool rounds. Without this, multi-step tool calls fail with a `400` on the second round — the OpenAI-compatible client drops the field by default.
- **monday.com outages** serve the last good snapshot, clearly marked stale in the response and the UI.
- **`/api/chat` is rate limited** to 10 requests per minute per IP so one tester can't exhaust the shared quota.
- **The dashboard needs no model at all**, so the core numbers stay available even when the LLM is throttled.

---

## Sample questions

The four chips in the UI cover the main paths, but these all work:

- How's our pipeline looking for energy this quarter?
- Which work orders are past end date but not completed?
- List the full execution backlog with sector and status.
- Summarise receivables and billed vs order value by sector.
- Draft a leadership update covering pipeline, execution, and risks.
- How many won deals have no work order raised?
- Compare Mining and Railways on win rate and open pipeline.

Clicking any dashboard tile, panel link, or table row sends a pre-filled question into the chat, so the two halves of the app stay connected.

---

## monday.com setup

1. Import each spreadsheet as its own board — `Deal funnel Data.xlsx` → **Deals**, `Work_Order_Tracker Data.xlsx` → **Work Orders**. For the Work Orders sheet, make sure the header row maps to column titles; if the import creates a header item anyway, the app removes it.
2. Generate a personal API token: monday.com avatar → **Developers** → **My access tokens**. Read access is sufficient — the agent never writes.
3. Get each board id from its URL: `monday.com/boards/<BOARD_ID>`.
4. Put all three values in `.env` (see below).

The app reads column values by title through the GraphQL API, so renaming or reordering columns on the board doesn't break it. Nothing is read from the Excel files at runtime.

---

## Running locally

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
# fill in your tokens, then:
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

### Environment variables

| Variable | Purpose |
|----------|---------|
| `MONDAY_API_TOKEN` | monday.com personal API token (read access) |
| `MONDAY_DEALS_BOARD_ID` | Deals board id |
| `MONDAY_WORK_ORDERS_BOARD_ID` | Work Orders board id |
| `LLM_PROVIDER` | `gemini` (default) or `openai` |
| `GEMINI_API_KEY` | Google AI Studio key |
| `GEMINI_MODEL` | Default `gemini-2.5-flash` |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | Optional alternative provider |

`.env` is gitignored. Settings are cached at startup, so restart the process after changing them.

### Tests

```bash
pytest
```

Ten tests, all covering messy-data behaviour rather than happy paths: sector-alias resolution, the "energy" umbrella, fiscal quarter and fiscal year boundaries, header-row detection, stage bucketing, join deduplication across duplicate masked names, backlog pagination, and the dashboard payload contract.

### Deployment notes

Any container host works (Railway, Render, Fly). Two things to configure:

- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Run a single worker.** The board cache and rate limiter are in-process; multiple workers would each keep their own copy.

---

## Known limitations

I'd rather state these than have a reviewer find them:

- **The cross-board join is fuzzy.** Masked deal names are the only available key, so distinct deals sharing a name can merge. Deduplication prevents inflated counts, but the join isn't exact and the agent discloses this.
- **Slippage is inferred from Probable End Date**, which is a plan rather than a contractual deadline. "Overdue" here means the plan has passed and the status isn't Completed.
- **The cache is in-memory**, so a restart re-fetches both boards. Appropriate for a single-instance demo; Redis would be the answer for real multi-instance traffic.
- **No trend history.** Every figure is point-in-time. Week-over-week deltas would need stored snapshots, which was out of scope for this build.
- **Free-tier inference.** Fine for evaluation, with failover to keep it usable, but a production deployment would use a paid tier or Vertex AI for predictable throughput and data handling.

---

## What I'd build next

1. Table rendering for lists inside chat answers, so a 48-row backlog is sortable instead of prose.
2. Snapshot history for week-over-week movement and threshold alerts.
3. Deep links from each row back to the monday.com item.
4. Role presets — Leadership, Delivery, Collections — changing the default view and suggested questions.

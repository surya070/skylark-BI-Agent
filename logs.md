# Skylark Drones — Assignment Work Log

Living log of decisions, progress, and next steps for the Monday.com Business Intelligence Agent assignment.

**Context:** Strong performance on this assignment is a hiring signal for Skylark Drones. Optimize for judgment, reliability, and founder-usable insights — not just “something that demos.”

---

## Hiring bar (how we decide)

What evaluators will likely notice:
1. **Product sense** — answers sound like something a founder would trust (insight + caveats, not raw dumps)
2. **Engineering judgment** — clear trade-offs, clean architecture, no hardcoded Excel
3. **Data maturity** — messy real-world data handled explicitly
4. **Ambiguity handling** — “leadership updates” interpreted thoughtfully and documented
5. **Ship quality** — hosted, stable, readable README + Decision Log

Decision principles:
- Prefer **solid + explainable** over flashy unfinished features
- Spend time on **query quality, data resilience, and cross-board BI**, not UI chrome
- Document every non-obvious trade-off (this becomes the Decision Log)
- Skip Monday “Bring your agent” — personal API token + our own hosted agent shows more ownership

---

## Assignment snapshot

**Task:** Build an AI agent that answers founder-level BI questions by reading live Monday.com boards (Work Orders + Deals).

**Deliverables:**
1. Hosted prototype (link, no local setup for testers)
2. Decision Log (≤2 pages)
3. Source code ZIP + README (architecture + Monday.com setup)

**Timeline:** 6 hours  
**Submit:** https://forms.gle/9wFwL5mdFbTXQtqq7

**Data files provided:**
- `Deal funnel Data.xlsx` — sheet `Deal tracker` (~347 deals, 12 columns)
- `Work_Order_Tracker Data.xlsx` — sheet `work order tracker` (~178 work orders; header on row 2, row 1 blank)

---

## Done so far

### 2026-08-25 — Kickoff & setup

- [x] Read assignment PDF (`Skylark Drones - Full stack Assignment - RVU.docx.pdf`)
- [x] Understood requirements: conversational BI agent, Monday.com integration, messy-data resilience, hosted demo, decision log, source ZIP
- [x] Inspected Excel structure (Deals headers clear; Work Orders needs blank row 1 removed / header on row 2)
- [x] Imported both Excel files into Monday.com as **separate boards**
- [x] Decided integration approach: **Monday.com GraphQL API** (not MCP)

### Decision: API over MCP

| Option | Pros | Cons |
|--------|------|------|
| **API (chosen)** | Works in hosted web apps; simple auth; full control over cleaning/errors | Manual GraphQL queries |
| MCP | Nice in Cursor/Claude Desktop | Harder to ship a public “open this link” prototype |

**Rationale:** Assignment requires a hosted, testable link without local setup. API fits that constraint; MCP does not as cleanly.  
**Hiring angle:** Owning the GraphQL client + data layer shows backend competence; “Bring your agent” / MCP would hide that behind Monday’s UI.

Also skipped Monday’s **“Bring your agent”** marketplace path — same reason: we want a candidate-owned hosted prototype, not a Monday-managed agent shell.

---

## Going to do (plan)

### 1. Monday.com API wiring
- [x] Create / copy Monday.com API token → stored in `.env` (gitignored)
- [x] Note Board IDs for Deals and Work Orders
- [x] Verify read access with GraphQL (`me` + `boards`)
- [ ] Confirm we never hardcode CSV/Excel into the agent — always fetch from Monday dynamically

**Verified boards:**
| Board | ID | Items |
|-------|-----|-------|
| Deal funnel Data | `5030842748` | 346 |
| Work_Order_Tracker Data | `5030842885` | 176 |

Auth check: API returns account `Surya Maheswaran` — connection OK.

### 2. Project scaffold
- [x] Chose stack: **FastAPI + simple HTML/CSS/JS chat** (Option B)
- [x] Agent: **OpenAI-compatible tool-calling** (not LangChain) — fewer moving parts for this scope
- [x] LLM: **Gemini 2.5 Flash free** (see LLM choice section)
- [x] Env config: `MONDAY_*`, `GEMINI_*` in `.env` (gitignored)
- [x] Modules: `monday_client`, `schema`, `analytics`, `agent`, `main` + `static/`
- [x] Smoke-tested chat against live monday.com
- [x] Explicit data-quality caveats in tool outputs / system prompt

### Decision: LangChain vs OpenAI tools
**Chose OpenAI-compatible function calling** (works for Gemini via Google’s compatible endpoint). LangChain helps for large multi-tool agent graphs; here we have explicit BI tools over 2 boards. Direct tool-calling is easier to debug, smaller dependency surface, and clearer for hiring reviewers.

### 3. Core agent capabilities
- [ ] Query understanding for founder-style questions (pipeline, sector, revenue, ops)
- [ ] Cross-board joins/lookups when useful (e.g. deal ↔ work order)
- [ ] Data resilience: missing values, inconsistent formats, communicate caveats
- [ ] Optional: “leadership updates” prep interpretation (document in Decision Log)

### 4. Hosting & polish
- [ ] Deploy prototype (e.g. Streamlit Cloud / Railway / Vercel — TBD)
- [ ] Smoke-test with sample founder questions
- [ ] Write `README.md` (architecture + Monday setup)
- [ ] Write Decision Log (≤2 pages)
- [ ] ZIP source and submit via Google Form

---

## Architecture audit — 2026-08-25

Verified live board data to test our assumptions. Architecture direction is sound; the tool layer has real gaps.

### Confirmed correct
- **API over MCP** — hosted-link requirement holds
- **LLM plans, Python computes** — all numbers come from `analytics.py`, never the model
- **Live Monday fetch** — no Excel/CSV in the code path
- **Direct tool-calling over LangChain** — 4 tools, explicit loop, easy to review

### Real values discovered on the boards

Deals `Sector/service`: Renewables (111), Mining (106), Railways (40), Others (28), Powerline (26), Construction (9), blank (8), DSP (7), Tender (5), Manufacturing (2), Security and Surveillance (1), Aviation (1) — **plus 2 rows literally containing the header text**.

Work Orders `Sector`: Mining (100), Renewables (51), Railways (13), Powerline (6), Others (4), Construction (2).

Deals `Deal Stage` is a lettered funnel: `A. Lead Generated` … `H. Work Order Received` … `L. Project Lost`, plus unlettered `Project Completed`.

### Gaps found (ordered by severity)

1. **"Energy sector" returns nothing.** The brief's own sample question is *"How's our pipeline looking for energy sector this quarter?"* — but no sector is named "energy". Substring filtering yields zero rows and the agent would confidently report "no energy pipeline". Needs a vocabulary-discovery tool plus semantic mapping (energy → Renewables + Powerline).
2. **No date filtering at all.** "This quarter" is unanswerable. `parse_date` exists but is never called. Available date fields: `Created Date`, `Tentative Close Date`, `Close Date (A)` on Deals; PO / start / end / invoice / collection dates on Work Orders.
3. **Header rows imported as items.** 2 Deals rows contain column titles as values — must be detected and excluded, and reported as a data-quality caveat.
4. **Revenue/collections ignored.** Work Orders carries 39 columns including `Amount Receivable`, `Collected Amount`, `Invoice Status`, `Collection status`, `Billing Status`. The brief explicitly asks about revenue; current tools only aggregate one amount field.
5. **No cross-board join.** Brief requires querying across both boards. Deals `name` and Work Orders `name` share deal identities (e.g. Sakura, Scooby-Doo) — a won-deal-to-execution join is the strongest BI story available.
6. **`search_*` returns whole records.** 39 columns × 25 rows per call inflates tokens and cost. Should project a relevant field subset.
7. **No graceful Monday failure.** API errors surface as HTTP 500. Should fall back to stale cache with an explicit caveat.
8. **Cold-start latency ~14s** for both boards (pagination + column lookups). Warm the cache at startup.
9. **`Closure Probability` is categorical** (`High`/`Medium`/`Low`), not numeric — cannot be used as a weighting factor as originally assumed.

### Fixes implemented and verified against live boards

New module `app/schema.py` holds all board vocabulary, sector aliases, fiscal-period parsing and messy-data helpers, keeping magic strings out of the analytics and agent layers.

| Gap | Fix | Verified result |
|-----|-----|-----------------|
| "energy" matched nothing | `resolve_sectors()` with alias and umbrella-term maps; every result carries an interpretation note | "energy" → Renewables + Powerline, **137 deals**, note surfaced to the user. "aerospace" → no match plus the list of real sectors |
| No date filtering | `resolve_period()` with Apr–Mar fiscal year; period + date-field arguments on every tool | "this_quarter" → Q2 FY26-27 (2026-07-01 to 2026-09-30); "last_fiscal_year" → FY25-26, 237 deals, 77.5% win rate |
| Header rows as data | `is_header_artifact()` applied at ingest | 2 rows dropped from Deals (346 → 344), reported in every response |
| Revenue ignored | `revenue_and_collections()` over five masked money columns | Order value 211.6M, billed 107.4M (50.7% of order value), receivables 36.3M, top exposures listed |
| No cross-board join | `pipeline_to_execution()` joining on normalised deal name | 100 won deals, 57 with work orders, **43 won with no work order**, 104 work orders whose deal isn't marked won |
| Whole records in search results | Field projection to a curated subset | Mining search of 25 records ≈ 14 KB instead of 39 columns per row |
| API failure returned HTTP 500 | `BoardSnapshot` with stale-cache fallback; freshness metadata on every tool result | Health reports `connected` / `degraded` / `unavailable`; chat never returns a stack trace |
| ~14s cold start | Startup warmup via FastAPI lifespan | First question hits a warm cache |

Two bugs found while testing the fixes themselves:

- **Work orders were double-counted** in the join. Masked names repeat (several deals named "Sakura"), so each matching deal pulled the same work orders. Deduplicating by work-order id changed the "Completed" count from an impossible 269 to 37.
- **Empty periods looked like dead business.** "Energy this quarter" legitimately returns zero rows because `Created Date` in the board spans 2024-08-09 to 2026-01-09 while today is Aug 2026. The scope block now tells the agent the actual date span so it reports the recency gap instead of implying no activity.

Kept deliberately: periods resolve against the real calendar, not the data's last date. Silently redefining "this quarter" to fit the data would be the wrong instinct for a tool executives rely on.

### Model decision (paid mini — superseded)

Earlier hire-bar analysis favoured a paid OpenAI mini for tool reliability. We later switched to **Gemini free** for assignment cost; see **LLM choice** below for the final call.

| Model | In / Out per 1M | Notes |
|-------|-----------------|-------|
| gpt-5-mini | $0.25 / $2.00 | Strong tool/reasoning fallback if Gemini free fails |
| gpt-4.1-mini | $0.40 / $1.60 | Solid paid fallback |
| gpt-4o-mini | $0.15 / $0.60 | Cheapest OpenAI; weaker tool selection |
| Claude Haiku 4.5 / frontier | $1+ / $5+ | Unjustifiable when Python does the math |

### Hugging Face options — evaluated and rejected

Tool-calling fine-tunes exist and are genuinely good at this shape of task: [xLAM-2](https://huggingface.co/Salesforce/Llama-xLAM-2-8b-fc-r), [ToolACE](https://huggingface.co/Team-ACE/ToolACE-8B), [watt-tool-8B](https://huggingface.co/watt-ai/watt-tool-8B), [Hammer2.1](https://huggingface.co/MadeAgents/Hammer2.1-7b), [Arch-Agent](https://huggingface.co/katanemo/Arch-Agent-1.5B).

Rejected for this deliverable because:
- On BFCL v4 (Aug 2026) the strong open models are large (Qwen3.5-397B, BTL-4 ≈ 73%); the self-hostable small ones drop sharply (Qwen3.5-4B ≈ 0.50, 2B ≈ 0.44)
- GPU hosting for a public demo costs far more than free API usage
- Tool-calling ability is only half the job — the agent also has to write a credible founder-facing narrative
- No model is trained on "Monday.com BI"; the domain logic lives in our Python tools regardless

Worth revisiting for data residency, high sustained volume, or fine-tuning on Skylark's actual schema and question log.

---

## Assumptions (running list)

1. Read-only Monday access is sufficient.
2. Two boards already exist in the candidate’s Monday workspace after Excel import.
3. Evaluators will test via hosted URL + may review source for dynamic Monday queries.
4. Messy/incomplete data is expected; agent should answer with caveats rather than fail hard.
5. Ambiguity (e.g. “leadership updates”) is intentional — document interpretation and proceed.
6. Gemini free-tier prompts may be used to improve Google products — acceptable for masked demo data; production would use paid/Vertex.

---

## LLM choice (final): Gemini 2.5 Flash

**Provider:** Google AI Studio (Gemini API), free tier  
**Model in production for this demo:** `gemini-2.5-flash`  
**Integration:** OpenAI-compatible endpoint (`generativelanguage.googleapis.com/v1beta/openai/`) so the existing tool-calling loop stays one code path.

**Flash failover chain (no Pro):** on HTTP **429 / 403 / 404**, `_llm_create` walks:
`gemini-2.5-flash` → `gemini-2.5-flash-lite` → `gemini-3.6-flash` → `gemini-3-flash-preview` → `gemini-3.5-flash` → `gemini-3.5-flash-lite` → `gemini-flash-latest` → `gemini-flash-lite-latest`

- Sticky: once a fallback succeeds, that model is preferred for later turns in the same process.
- User-facing quota error only if **every** Flash model in the chain fails (lists which were tried).
- Rationale: free-tier RPM/RPD is often **per-model**; failing over keeps the demo alive when 2.5 Flash is exhausted mid-evaluation. Combined with `/api/chat` rate limit (10/60s per IP).

### Why Gemini (not HF small / not paid OpenAI)
- **$0 inference** for evaluator traffic; companies read that as cost-aware.
- **Hosted reliability** without GPU ops (vs ToolACE/xLAM/Hammer self-host).
- BI correctness still lives in **Python tools** — the model only plans + narrates.
- Recruiter answer if asked “why not a small open model?”: small models win tool-syntax benches; we need multi-step tools + founder narrative + a public demo URL. Self-host costs more than free Flash for this volume.

### Why **2.5 Flash** specifically (not Pro, not only 3.x)
| Option | Verdict |
|--------|---------|
| **gemini-2.5-flash (chosen)** | Best free-tier fit for this agent: confirmed **text + function calling** on our working AI Studio key; generous free quota vs Pro; low latency; stable for multi-tool BI loops. Live smoke test (Mining pipeline) returned correct tool-backed figures. |
| gemini-3.6-flash / 3 Flash | Also works on the new key; kept as fallback. Prefer 2.5 as primary because it returned cleaner short answers in our probe and matches the well-documented free Flash tier we planned around. |
| gemini-*-pro / pro-latest | Rejected for default: burns free quota faster, overkill when analytics are deterministic, and earlier project hit Pro 429 quickly. |
| First AI Studio key (`AQ.…`) | Blocked: Flash **403**, 2.5 **404** (“not available to new users”), Pro **429**. Replaced with a standard `AIza…` key — then 2.5 Flash worked. |

### Constraints on the model
- System: read-only, BI scope only, no invented numbers, masked money, tools-first, jailbreak ignore
- Runtime: temperature 0.1, max output tokens, max history turns, message length cap, off-topic regex prefilter, search limit clamp, tool-round cap
- **Quota resilience:** auto Flash failover on 429/403/404 + chat rate limit; clearer error only after full chain exhausted

### Verification (2026-08-25)
- Health: `gemini:gemini-2.5-flash`, monday.com connected (344 deals / 176 WOs)
- Chat: “How is Mining pipeline looking?” → 106 deals, 57 open, 31 won, 73.8% win rate on decided deals (from tools)

---

## Architecture review (2026-08-25)

Verdict: **direction is right for the brief and for a hire sample.** The important bets (API over MCP, LLM plans / Python computes, live Monday fetch, Flash free over self-host) should stay. The product is **not submission-complete** until hosted URL + README + Decision Log exist.

### Decisions that should stay

| Decision | Why it still holds |
|----------|-------------------|
| Monday GraphQL API, not MCP / Bring-your-agent | Required public hosted link; shows ownership of the data layer |
| FastAPI + static HTML | Reviewable, shippable in remaining time; UI is not the scoring centre |
| Tool-calling, not LangChain | Explicit loop, easy to debug, matches two-board scope |
| Deterministic `analytics.py` | Numbers cannot be hallucinated; this is the core BI pattern |
| `schema.py` vocabulary + fiscal year | Fixes the brief’s own “energy this quarter” example |
| Gemini 2.5 Flash free | $0 demo inference; tool calling verified; Pro is overkill |
| 120s cache + stale fallback | Latency + honesty when Monday is down |

### Could-be-betters (ranked)

**Do before submit (blocks the grade):**
1. Hosted URL, README, ≤2-page Decision Log, ZIP without `.env`
2. Confirm evaluators can hit Gemini free quota — mitigated by Flash failover + `/api/chat` rate limit (10/60s); still monitor during demo day

**Do if 30–60 minutes remain (hire signal):**
3. Dedicated `prepare_leadership_brief` tool that returns a structured JSON brief — currently leadership updates are prompt-only
4. Light markdown rendering in the UI (headings/bullets) with `textContent`/sanitised HTML — answers currently look like a wall of text
5. Return `tools_used` + data freshness on `/api/chat` so the UI can show trust chips
6. Drop unused `google-genai` from `requirements.txt` (we use OpenAI-compatible client only)
7. A few unit tests on `resolve_sectors`, `resolve_period`, header-row drop, join dedup — proves we treat messy data as a contract

**Do not do in remaining time:**
- Rewrite on Next.js / LangChain / self-hosted HF
- Switch to native Gemini SDK unless the OpenAI-compat path breaks
- Auth, write-back to Monday, multi-worker Redis cache
- Heavy chart libraries (CSS bars on the pulse dashboard are enough)

### Residual risks (honest)

- **Join key is masked deal name** — collisions (Sakura × N) are handled by WO id dedup, but the join is still fuzzy. Say so in the Decision Log.
- **In-memory Monday cache** dies on process restart / multiple workers. Fine for a single Railway/Render instance; document “one worker”.
- **`get_settings` is `@lru_cache`** — env changes need a process restart (already noted).
- **Off-topic regex** can refuse a legitimate question that contains “sql” / “hack”. Prefer letting the system prompt refuse; regex is a quota saver, not a security boundary.
- **Free-tier Gemini data-use** — already documented; keep in Decision Log.

---

## Further scope (next)

### Must ship for submission
1. [x] **Working Gemini key** + `gemini-2.5-flash` verified end-to-end
2. **Hosted deploy** (Railway / Render / Fly) with env vars; public URL
3. **README** — architecture, Monday setup, env vars, sample questions
4. **Decision Log (≤2 pages)** — lift from this file’s audit + model rationale
5. **ZIP + Google Form submit**

### Polish (hire bar)
6. [x] Light markdown rendering for agent answers (safe client-side subset)
7. [x] Show tools used + data freshness on each reply
8. [x] Rate-limit `/api/chat` (10 / 60s per IP)
9. [x] Drop unused `google-genai` from requirements
10. [x] Unit tests (`tests/test_schema_analytics.py` — 9 passing)
11. [x] `prepare_leadership_brief` tool (structured leadership pack)
12. [x] `list_execution_backlog` tool — full paginated overdue WO list (fixes “cannot list all 43”)
13. [x] Minimal ops pulse dashboard above chat (`/api/dashboard` + ask-into-agent CTAs)

### Known bug / failure risks to watch
| Risk | Mitigation status |
|------|-------------------|
| Gemini invents this_quarter on overall asks | Prompt: omit period unless asked; auto all-time fallback when period returns 0 rows |
| Bad / blocked Gemini project key | Mitigated: new `AIza` key; 2.5 Flash verified. Rotate keys after submit |
| Gemini free-tier 429 on primary model | Auto-failover across Flash chain; sticky last-good; error only if all fail |
| Process env overriding `.env` | Restart without stale `GEMINI_API_KEY` env; prefer file values |
| Malformed tool JSON from model | Clamp/parse args; empty dict fallback |
| Multi-round tool loops burn free RPM | Cap rounds at 5; suggest narrower asks |
| “This quarter” empty because data ends Jan 2026 | Scope returns date span hint |
| Duplicate deal names inflate joins | Deduped by work-order id |
| Header rows as data | Dropped at ingest |
| Stale Monday during outage | Cache fallback + freshness warning |
| Free-tier prompts may train Google | Documented; OK for masked demo data |
| Secrets in chat history | Rotate Monday + Gemini keys after submit |
| Settings cached at process start | Restart server after `.env` changes |
| Gemini 3.x empty/short replies with low max_tokens | Prefer 2.5 Flash; raise max_tokens if switching to 3.x |

---

## Open questions / TBD

- Hosting target (Railway vs Render vs Fly)
- Final Decision Log wording for “leadership updates”
- Whether to add answer markdown rendering before submit

---

## Notes from data inspection

**Deals columns:** Deal Name, Owner code, Client Code, Deal Status, Close Date (A), Closure Probability, Masked Deal value, Tentative Close Date, Deal Stage, Product deal, Sector/service, Created Date

**Work Orders (sample columns):** Deal name masked, Customer Name Code, Serial #, Nature of Work, Execution Status, Data Delivery Date, Date of PO/LOI, Document Type, Probable Start/End Date, BD/KAM Personnel code, Sector, Type of Work, invoice fields, masked amount fields, etc.

---

## Usability evaluation (2026-08-25)

**Verdict:** Strong for ad-hoc leadership Q&A and pre-meeting briefs; weak as a daily ops surface. Chat fastracks discovery and narrative; a glanceable dashboard fastracks monitoring and triage. Target product: **dashboard for the known pulse + chat for the unexpected question**.

### Tasks this tool accelerates

| Job | Speedup vs Monday + spreadsheet |
|-----|----------------------------------|
| Sector / period pipeline (“energy this quarter”) | High |
| Leadership update from both boards | Very high |
| Overdue / execution slippage list | High |
| Collections / billed vs order by sector | High |
| Won deals vs work orders / CRM gaps | High (unique) |
| Named deal/WO lookup | Medium |
| Recurring weekly pulse of the same KPIs | Low (re-ask friction) |

### Usability notes

**Works:** suggested chips, tools/freshness trust chips, tools-first BI, leadership brief path.  
**Friction:** blank-box tax after chips; long lists as prose; no pinned views/alerts; no WoW trends; multi-tool latency; no Monday deep links.

**Personas:** founder/leadership excellent; BD/KAM good; ops daily triage mediocre without tables; finance good for overview.

### Product direction decided

Ship a **minimal operations pulse** above chat (no chart library): attention metrics → sector/funnel bars → backlog + receivables tables → “Ask about this” into the agent. Dashboard owns monitoring; chat owns narrative and long-tail cuts.

### Ranked follow-ups (post-minimal dashboard)

1. Table renders inside chat for backlog/search results  
2. Follow-up chips from leadership brief  
3. Monday deep links per deal/WO  
4. Role presets (Leadership / Ops / Collections)  
5. Later: snapshots/WoW, alerts, owner-scoped views  

---

## Final architecture review (2026-08-25, pre-submission)

**Verdict: the build is submit-ready; the submission is not.** Every engineering decision still holds and the code is clean, tested, and live against monday.com. What blocks submission is packaging: **hosted URL, README, Decision Log, ZIP** — all three deliverables in the brief.

### Decisions re-confirmed (no change recommended)

| Decision | Still correct because |
|----------|-----------------------|
| Monday GraphQL API, not MCP / Bring-your-agent | Brief demands a hosted link testers can open; also shows we own the data layer |
| LLM plans, Python computes (`analytics.py`) | No figure can be hallucinated — the core BI credibility argument |
| Direct tool-calling, not LangChain | 9 tools, one explicit loop, reviewable in minutes |
| `schema.py` vocabulary + fiscal Apr–Mar | Solves the brief's own "energy this quarter" example |
| FastAPI + static HTML/CSS/JS | Shipped inside budget; UI is not the scoring centre |
| Gemini Flash free tier | $0 evaluator inference; tool calling verified end-to-end |
| 120s cache + stale fallback | Latency plus honesty when Monday is unreachable |
| Dashboard (`/api/dashboard`) computes with **no LLM** | Pulse is always correct and fast even when Gemini is throttled |

### Reliability work that materially de-risks demo day
- Flash failover on **403 / 404 / 429 / 503** plus **22s per-attempt timeout**; slow aliases (`flash-latest`) removed from the chain and never made sticky
- Gemini 3.x **`thought_signature`** echoed on tool rounds (was a hard 400 on the second round)
- Period guard: model must not invent `this_quarter`; empty periods auto-fall back to all-time with a caveat
- `/api/chat` rate limit 10 req / 60s per IP

### Health check at review time
- `pytest`: **10 passed**; no linter errors across `app/`, `static/`, `tests/`
- Routes: `/`, `/api/health`, `/api/dashboard`, `/api/chat`
- Live: 344 deals / 176 work orders; 145 open, 70.4% win rate, 48 overdue WOs — chat matches the dashboard
- Cleanups this pass: dead branch removed from `_llm_create`; `.env.example` corrected to `gemini-2.5-flash`

### Accepted limitations (state these in the Decision Log, do not fix now)
- Cross-board join is on **normalised masked deal name** — fuzzy; WO-id dedup prevents double counting
- **In-memory** cache and rate limiter — deploy with **one worker**
- `get_settings` is `@lru_cache` — env changes need a restart
- Free-tier quota is per project and resets at **midnight Pacific**; failover mitigates but cannot remove the ceiling

### Blocking checklist before hitting submit
1. Deploy (Railway / Render / Fly), one worker, env vars set → capture public URL
2. [x] `README.md` — architecture, Monday setup, env vars, sample questions, limitations
3. [x] `DecisionLog.docx` — 2 pages, 1244 words; decisions table, leadership-update interpretation, messy data, reliability, out-of-scope, limitations
4. Paste the hosted URL into the README placeholder (`REPLACE_WITH_HOSTED_URL`)
5. ZIP **without** `.env`, `.venv/`, `.pytest_cache/`
6. Rotate `MONDAY_API_TOKEN` and `GEMINI_API_KEY` after submission (both appeared in chat)

---

## Changelog

| When | What |
|------|------|
| 2026-08-25 | Created `logs.md`; recorded PDF review, Excel import, API-vs-MCP decision, and forward plan |
| 2026-08-25 | Added hiring-bar decision principles; reinforced API (not MCP / “Bring your agent”) |
| 2026-08-25 | Stored Monday API token in `.env`; verified GraphQL fetch; captured board IDs |
| 2026-08-25 | Scaffolded FastAPI + HTML app; chose OpenAI tools over LangChain; health route wired |
| 2026-08-25 | Architecture audit against live board data; found sector-vocabulary and date-filter gaps; evaluated and rejected Hugging Face tool models |
| 2026-08-25 | Implemented all audit fixes: `schema.py` vocabulary layer, fiscal periods, header-row exclusion, revenue/collections tool, cross-board join, stale-cache fallback, startup warmup. Model choice deferred |
| 2026-08-25 | Integrated Gemini free tier + constraints; professional UI; first key blocked (403/429/404) |
| 2026-08-25 | New `AIza` Gemini key verified; **chose `gemini-2.5-flash`** (tool calling + free tier); 3.x Flash as fallback; Pro rejected; Mining E2E chat passed; LLM rationale written for Decision Log |
| 2026-08-25 | Full architecture review: keep current bets; submission still blocked on host/README/Decision Log; listed could-be-betters vs explicit non-goals |
| 2026-08-25 | Polish: leadership brief tool, full backlog listing, markdown UI, tools/freshness meta, chat rate limit, drop google-genai, 9 unit tests |
| 2026-08-25 | Gemini 429 now auto-fails over across Flash models (2.5 → lite → 3.x → flash-latest); sticky last-good model |
| 2026-08-25 | Logged usability evaluation: chat vs dashboard jobs; decided minimal pulse dashboard + ask-into-chat |
| 2026-08-25 | Minimal ops dashboard: `/api/dashboard`, pulse/funnel/overdue bars, backlog + receivables tables, ask CTAs |
| 2026-08-25 | Split layout: dashboard left / chat right; fix invented this_quarter emptying overall pipeline asks |
| 2026-08-25 | Echo Gemini `thought_signature` on tool rounds (fixes 400 on gemini-3.x); prefer 2.5 before 3.x fallbacks |
| 2026-08-25 | Faster chat: drop flash-latest sticky, 22s per-model timeout, shorter fallback chain, lower max tokens |
| 2026-08-25 | Final pre-submission architecture review: all decisions hold; removed dead failover branch; fixed `.env.example` model; submission still blocked on host/README/Decision Log/ZIP |
| 2026-08-25 | Wrote `README.md` (architecture, messy-data handling, Monday setup, sample questions, limitations) and `DecisionLog.docx` (2 pages, 1244 words) |

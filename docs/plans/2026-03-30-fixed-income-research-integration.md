# Fixed-Income + Research Reports Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add high-value fixed-income and research-report capabilities to stock-mcp for both MCP and REST, with AI-friendly structured outputs and simple configurable database integration.

**Architecture:** Extend the existing stock-mcp gateway-first architecture with a dedicated fixed-income domain slice and a lightweight outbound client to the sibling `news-mcp` service for research reports. Keep market data inside stock-mcp adapters/use-cases, but consume 研报 through a service boundary rather than duplicating MySQL access, so ownership stays clear and deployment remains modular.

**Tech Stack:** FastAPI, FastMCP, dependency-injector, pydantic-settings, AkShare, existing MarketGateway routing, sibling news-mcp REST client using httpx/aiohttp style async HTTP.

---

## Recommendation Summary

Ship this in three phases:

1. **Phase 1: fixed-income foundations inside stock-mcp**
   - Build a dedicated fixed-income tool group and REST route group.
   - Start with the highest-AI-value datasets already accessible from AkShare or existing adapter patterns: treasury yield curve normalization, convertible bonds uplift, bond ETF/fund bridge, stock option chain/Greeks, and PCR/IV term-structure style summaries.
   - Normalize all outputs into explicit instrument metadata + term/expiry/strike dimensions + summary blocks.

2. **Phase 2: research-report integration via sibling news-mcp API**
   - Add a `ResearchReportClient` in stock-mcp that calls `news-mcp` `/research/search` and optionally later MCP if needed.
   - Add stock-mcp fixed-income aware research endpoints/tools that support filtering by ticker, title, institution, report type, and date range, with output shaped for LLM consumption.
   - Prioritize bond/fixed-income categories (`债券研究`, `宏观经济`, `投资策略`, `行业研究`) and security-linked reports.

3. **Phase 3: composite AI research outputs**
   - Add “fixed-income research pack” style aggregation that combines yield curve, options sentiment, convertible-bond context, and curated research-report excerpts/citations.
   - Keep this as orchestration only after primitives are stable.

This is the best path because it keeps **market data authoritative in stock-mcp**, **research-report data authoritative in news-mcp**, avoids coupling stock-mcp directly to the sibling MySQL schema, and fits the existing route/tool/use-case architecture with minimal architectural churn.

---

## Why this integration approach is recommended

### Preferred sibling-repo integration: REST API client

Use a **stock-mcp outbound client to news-mcp REST API**, not direct MySQL access and not code-importing the sibling repo.

**Why REST client is best:**
- `news-mcp` already exposes `/research/search` at `C:\Users\zheyu\Documents\dev\tools\news-mcp\src\server\api\routes\research.py:13-99`.
- The MySQL details and query semantics already live in `news-mcp` at `C:\Users\zheyu\Documents\dev\tools\news-mcp\src\server\domain\sources\mysql_research_source.py:25-360`.
- Stock-mcp is currently Postgres-oriented for its own persistence (`C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\config\settings.py:106-133`) and should not gain a second database integration just to read sibling-owned data.
- REST gives independent deployment and schema evolution. If the research table changes, only news-mcp needs to adapt.
- It also enables later replacement with a remote service without changing stock-mcp callers.

**Why not direct DB access from stock-mcp:**
- Duplicates ownership of the `ifindyb` schema and filtering rules.
- Forces stock-mcp to add MySQL settings, connection lifecycle, query code, and tests for a sibling data source it does not own.
- Makes stock-mcp harder to deploy and reason about.

**Why not import sibling Python modules directly:**
- Cross-repo imports are brittle in local/dev/prod packaging.
- Couples release cadence and runtime path assumptions.

---

## Simple configuration recommendation

The user asked for database address to be configurable, but simple.

Recommended config model:

- Keep stock-mcp’s own DB config unchanged for Postgres/security master.
- Add only **service endpoint config** for research integration in stock-mcp:
  - `RESEARCH_REPORTS_ENABLED=true`
  - `RESEARCH_REPORTS_BASE_URL=http://127.0.0.1:9899`
  - `RESEARCH_REPORTS_TIMEOUT_SECONDS=8`
- Keep the actual MySQL/database address configurable **inside news-mcp only**, where it already belongs:
  - `DATABASE__CONNECTION_STRING=...`

This preserves the user requirement while avoiding duplicated DB config across repos.

---

## Existing codebase fit

Relevant stock-mcp architecture points:

- App/router registration lives in `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\app.py:26-42` and `:181-220`.
- DI container is in `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\core\dependencies.py:47-247`.
- Adapter bootstrap/registration is in `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\core\bootstrap.py:24-130`.
- MCP tool groups are registered in `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\mcp\registry.py:47-196`.
- Unified dispatch is via `MarketGateway` method registries in `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\domain\market_gateway.py:52-175`.
- Existing bond-related fragments already exist but are buried in money-flow:
  - REST `bond-yield` / `convertible-bond` / `institutional-research` in `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\api\routes\money_flow.py:433-543`
  - MCP `get_bond_yield` in `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\mcp\tools\money_flow_tools.py:2576-2613`
  - AkShare adapter `get_bond_yield` in `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\domain\adapters\akshare_adapter.py:2996-3024`

That means the best plan is **not** to start from zero. Instead, carve out a proper fixed-income vertical and move/expand the most relevant bond/options capabilities under it.

---

## Scope split

### Phase 1: Fixed-income primitives in stock-mcp

Deliverables:
- Dedicated fixed-income MCP tool group.
- Dedicated fixed-income REST route group.
- Normalized response models for:
  - treasury yield curve / term spread snapshot
  - convertible bond detail/listing and equity linkage
  - stock option chain by underlying
  - per-contract Greeks
  - derived sentiment metrics: PCR by expiry, ATM IV snapshot, basic skew/term summary
- Fact-pack-friendly artifact shape for LLMs.

### Phase 2: Research-report integration

Deliverables:
- `ResearchReportClient` in stock-mcp calling news-mcp `/research/search`.
- REST + MCP accessors in stock-mcp for:
  - search research reports by ticker / institution / title / date range
  - fixed-income-focused report search presets
  - report digest/excerpt formatting for AI consumption
- Citation-preserving markdown/json outputs.

### Phase 3: Composite fixed-income research pack

Deliverables:
- One high-value MCP tool and one REST endpoint producing a fixed-income research pack that combines:
  - current rates context
  - option sentiment/volatility context
  - convertible-bond linkage where relevant
  - recent research-report evidence with citations

Keep Phase 3 orchestration-only; do not add it until primitives from Phases 1-2 are stable and tested.

---

## Likely files to modify in stock-mcp

### Configuration / dependency wiring

**Modify:**
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\config\settings.py`
  - Add nested settings model for research report service URL/timeout/enabled flag.
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\core\dependencies.py`
  - Register `ResearchReportClient` singleton/factory.
  - Register new fixed-income service if used.
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\app.py`
  - Include new fixed-income router.
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\mcp\registry.py`
  - Register a `fixed-income` tool group.

### Gateway / adapter layer

**Modify:**
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\domain\market_gateway.py`
  - Add new method names to `_TICKER_METHODS` / `_MARKET_METHODS` for option-chain / Greeks / PCR / fixed-income research primitives.
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\domain\adapters\base.py`
  - Add abstract methods for the new option/fixed-income operations.
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\domain\adapters\akshare_adapter.py`
  - Implement the new AkShare-backed option-chain and Greeks fetchers.
  - Improve `get_bond_yield` normalization and summary output.

### Use cases / services

**Modify or create:**
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\core\use_cases\money_flow.py`
  - Remove future fixed-income creep over time; only keep compatibility wrappers if needed.
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\core\use_cases\fixed_income.py` (new)
  - New use-case module wrapping gateway + research-report client.
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\domain\services\fixed_income_service.py` (new, optional)
  - Add only if shared summarization/normalization becomes large enough to justify it.
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\domain\types.py`
  - Extend/introduce typed response models if this repo is using them for structured artifacts.

### REST / MCP surfaces

**Create:**
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\api\routes\fixed_income.py`
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\mcp\tools\fixed_income_tools.py`

**Modify:**
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\api\routes\preview.py`
  - If preview workbench enumerates tools, add fixed-income entries.
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\utils\openapi_generator.py`
  - Add tool-to-tag mappings.
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\mcp\server.py`
  - If static descriptions/tool tags are duplicated there, update accordingly.

### Research integration client

**Create:**
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\infrastructure\clients\research_reports_client.py`

This client should:
- call news-mcp `/research/search`
- expose stock-mcp-friendly methods such as:
  - `search_reports(...)`
  - `search_fixed_income_reports(...)`
  - `search_security_reports(...)`
- normalize the returned markdown/json into citation-safe structured records

### Tests

**Create:**
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_fixed_income_api.py`
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_fixed_income_tools.py`
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_research_reports_client.py`
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_fixed_income_use_cases.py`

**Likely modify:**
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_preview.py`
- `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_response_contract.py`

---

## Detailed plan by task

### Task 1: Define fixed-income API surface and naming

**Files:**
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\mcp\registry.py`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\app.py`
- Create: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\api\routes\fixed_income.py`
- Create: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\mcp\tools\fixed_income_tools.py`
- Test: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_fixed_income_api.py`
- Test: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_fixed_income_tools.py`

**Step 1: Write failing API/router tests**

Test that these endpoints exist and return mocked payloads:
- `GET /api/v1/fixed-income/yield-curve`
- `GET /api/v1/fixed-income/convertible-bonds`
- `GET /api/v1/fixed-income/options/chain`
- `GET /api/v1/fixed-income/options/greeks`
- `GET /api/v1/fixed-income/research-reports`
- `POST /api/v1/fixed-income/research-pack`

Also test MCP registration for tools such as:
- `get_yield_curve_snapshot`
- `get_convertible_bond_snapshot`
- `get_stock_option_chain`
- `get_stock_option_greeks`
- `search_fixed_income_research_reports`
- `build_fixed_income_research_pack`

**Step 2: Run tests to verify they fail**

Run:
```bash
uv run pytest tests/test_fixed_income_api.py tests/test_fixed_income_tools.py -v
```

Expected: FAIL with missing router/tool registration.

**Step 3: Add empty router/tool skeletons**

Create the route and tool modules with minimal stub handlers returning a placeholder envelope shape consistent with `rest_response` and artifact responses.

**Step 4: Register them**

- Include router in `app.py` near other route imports/registrations.
- Add `fixed-income` `ToolGroup` in `registry.py`.

**Step 5: Run tests to verify skeleton wiring passes**

Run:
```bash
uv run pytest tests/test_fixed_income_api.py tests/test_fixed_income_tools.py -v
```

Expected: PASS for existence/registration tests.

**Step 6: Commit**

```bash
git add src/server/app.py src/server/mcp/registry.py src/server/api/routes/fixed_income.py src/server/mcp/tools/fixed_income_tools.py tests/test_fixed_income_api.py tests/test_fixed_income_tools.py
git commit -m "feat: add fixed-income API and MCP skeletons"
```

---

### Task 2: Normalize treasury yield curve into AI-usable structure

**Files:**
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\domain\adapters\akshare_adapter.py:2996-3024`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\mcp\tools\fixed_income_tools.py`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\api\routes\fixed_income.py`
- Test: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_fixed_income_use_cases.py`

**Step 1: Write failing normalization tests**

Test for output fields like:
```python
assert data["curve_type"] == "china_treasury"
assert data["latest_date"] == "2026-03-28"
assert data["tenors"] == ["3M", "6M", "1Y", "3Y", "5Y", "10Y", "30Y"]
assert data["spreads"]["10Y-2Y"] == 0.31
assert "summary" in data
```

Also assert no malformed key like existing `" curves"` typo survives.

**Step 2: Run the specific test**

Run:
```bash
uv run pytest tests/test_fixed_income_use_cases.py::test_yield_curve_normalization -v
```

Expected: FAIL.

**Step 3: Implement minimal normalization**

Refactor AkShare raw output into:
- `curve_type`
- `source`
- `latest_date`
- `points` as `{tenor, yield}` rows
- `spreads`
- `inversion_flags`
- `summary`

Do not keep raw table shape as the primary response.

**Step 4: Expose through fixed-income MCP and REST endpoints**

Ensure both surfaces return the same normalized data block.

**Step 5: Run tests**

Run:
```bash
uv run pytest tests/test_fixed_income_use_cases.py::test_yield_curve_normalization tests/test_fixed_income_api.py::test_yield_curve_endpoint -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add src/server/domain/adapters/akshare_adapter.py src/server/api/routes/fixed_income.py src/server/mcp/tools/fixed_income_tools.py tests/test_fixed_income_use_cases.py tests/test_fixed_income_api.py
git commit -m "feat: normalize treasury yield curve outputs"
```

---

### Task 3: Add stock option chain and Greeks primitives

**Files:**
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\domain\adapters\base.py`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\domain\adapters\akshare_adapter.py`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\domain\market_gateway.py`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\api\routes\fixed_income.py`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\mcp\tools\fixed_income_tools.py`
- Test: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_fixed_income_api.py`
- Test: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_fixed_income_tools.py`

**Step 1: Write failing tests for option chain and Greeks**

Test normalized fields like:
```python
assert payload["underlying"] == "510050"
assert payload["expiries"]
assert payload["contracts"][0]["strike"]
assert payload["contracts"][0]["option_type"] in {"call", "put"}
assert payload["contracts"][0]["delta"] is not None
assert payload["summary"]["put_call_ratio"] is not None
```

**Step 2: Run tests to verify failure**

Run:
```bash
uv run pytest tests/test_fixed_income_api.py -k option -v
```

Expected: FAIL.

**Step 3: Implement AkShare-backed fetchers**

Use AkShare option APIs to add methods conceptually like:
- `get_stock_option_chain(underlying, expiry=None)`
- `get_stock_option_greeks(contract_code)` or batched per chain
- derived summary helper for PCR / ATM IV / skew hints

Normalize data into explicit dimensions:
- `underlying`
- `exchange`
- `expiry`
- `strike`
- `option_type`
- `last_price`
- `open_interest`
- `volume`
- `implied_volatility`
- `delta/gamma/theta/vega/rho`

**Step 4: Register gateway methods**

Add the new method names into `MarketGateway` registries in `market_gateway.py`.

**Step 5: Expose REST and MCP**

REST should support query params by underlying and expiry.
MCP should support markdown and json outputs, with a compact AI-facing summary plus artifact table payload.

**Step 6: Run tests**

Run:
```bash
uv run pytest tests/test_fixed_income_api.py tests/test_fixed_income_tools.py -k option -v
```

Expected: PASS.

**Step 7: Commit**

```bash
git add src/server/domain/adapters/base.py src/server/domain/adapters/akshare_adapter.py src/server/domain/market_gateway.py src/server/api/routes/fixed_income.py src/server/mcp/tools/fixed_income_tools.py tests/test_fixed_income_api.py tests/test_fixed_income_tools.py
git commit -m "feat: add stock option chain and greeks tools"
```

---

### Task 4: Promote convertible bonds into fixed-income-first outputs

**Files:**
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\api\routes\money_flow.py:433-441`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\api\routes\fixed_income.py`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\mcp\tools\fixed_income_tools.py`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\domain\adapters\akshare_adapter.py`
- Test: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_fixed_income_api.py`

**Step 1: Write failing tests for convertible bond normalization**

Assert fields like:
```python
assert data["bond_code"] == "110059"
assert data["underlying_stock"] == "SSE:600887"
assert data["conversion_price"] is not None
assert data["premium_rate"] is not None
assert data["maturity_date"]
```

**Step 2: Run tests**

Run:
```bash
uv run pytest tests/test_fixed_income_api.py::test_convertible_bond_endpoint -v
```

Expected: FAIL.

**Step 3: Implement normalized response**

Do not expose raw AkShare columns as the public contract. Add a clean bond-linked structure with equity linkage and valuation summary.

**Step 4: Keep compatibility path**

The old money-flow endpoint may remain temporarily, but fixed-income route/tool becomes the preferred documented surface.

**Step 5: Run tests**

Run:
```bash
uv run pytest tests/test_fixed_income_api.py::test_convertible_bond_endpoint -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add src/server/api/routes/money_flow.py src/server/api/routes/fixed_income.py src/server/mcp/tools/fixed_income_tools.py src/server/domain/adapters/akshare_adapter.py tests/test_fixed_income_api.py
git commit -m "feat: normalize convertible bond outputs for fixed-income"
```

---

### Task 5: Add research report service client to stock-mcp

**Files:**
- Create: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\infrastructure\clients\research_reports_client.py`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\config\settings.py`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\core\dependencies.py`
- Test: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_research_reports_client.py`

**Step 1: Write failing client tests**

Mock the sibling service HTTP call and assert:
```python
assert result["count"] == 2
assert result["results"][0]["title"]
assert result["results"][0]["organization"]
assert result["results"][0]["publish_date"]
assert result["results"][0]["citations"][0]["source"] == "news-mcp"
```

Also test disabled/unconfigured mode returns a safe structured error.

**Step 2: Run tests**

Run:
```bash
uv run pytest tests/test_research_reports_client.py -v
```

Expected: FAIL.

**Step 3: Implement minimal async client**

Client behavior:
- read `RESEARCH_REPORTS_ENABLED`, `RESEARCH_REPORTS_BASE_URL`, `RESEARCH_REPORTS_TIMEOUT_SECONDS`
- call `GET {base_url}/research/search`
- request `output_format=json`
- normalize fields for stock-mcp
- preserve title / organization / author / publish date / ticker / report_type / excerpt

**Step 4: Wire into DI**

Register in `dependencies.py` as a singleton/factory.

**Step 5: Run tests**

Run:
```bash
uv run pytest tests/test_research_reports_client.py -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add src/server/infrastructure/clients/research_reports_client.py src/server/config/settings.py src/server/core/dependencies.py tests/test_research_reports_client.py
git commit -m "feat: add research report service client"
```

---

### Task 6: Expose research-report search in stock-mcp fixed-income endpoints

**Files:**
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\api\routes\fixed_income.py`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\mcp\tools\fixed_income_tools.py`
- Create: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\core\use_cases\fixed_income.py`
- Test: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_fixed_income_api.py`
- Test: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_fixed_income_tools.py`

**Step 1: Write failing tests**

Test searches by:
- ticker
- institution
- title keyword
- date range
- fixed-income preset categories (`债券研究`, `宏观经济`, `投资策略`)

Assert output includes citations and excerpt-safe markdown/json.

**Step 2: Run tests**

Run:
```bash
uv run pytest tests/test_fixed_income_api.py tests/test_fixed_income_tools.py -k research -v
```

Expected: FAIL.

**Step 3: Implement minimal fixed-income report search use case**

Use the client and apply stock-mcp-side defaults:
- if no report_type provided, fixed-income preset should search categories in priority order
- optional bond/security keyword enrichment when ticker or title hints at bonds/options/rates

**Step 4: Expose REST and MCP**

REST endpoint returns `rest_response(data=...)`.
MCP tool returns compact summary + artifact list with citations.

**Step 5: Run tests**

Run:
```bash
uv run pytest tests/test_fixed_income_api.py tests/test_fixed_income_tools.py -k research -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add src/server/api/routes/fixed_income.py src/server/mcp/tools/fixed_income_tools.py src/server/core/use_cases/fixed_income.py tests/test_fixed_income_api.py tests/test_fixed_income_tools.py
git commit -m "feat: expose fixed-income research report search"
```

---

### Task 7: Add composite fixed-income research pack

**Files:**
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\core\use_cases\fixed_income.py`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\api\routes\fixed_income.py`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\mcp\tools\fixed_income_tools.py`
- Test: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_fixed_income_use_cases.py`

**Step 1: Write failing orchestration test**

Test one endpoint/tool that composes:
- yield curve snapshot
- option sentiment summary
- convertible bond snapshot if symbol provided
- research reports digest

Assert stable top-level shape:
```python
assert payload["market_context"]
assert payload["derivatives_context"]
assert payload["research_evidence"]
assert payload["citations"]
```

**Step 2: Run test**

Run:
```bash
uv run pytest tests/test_fixed_income_use_cases.py::test_build_fixed_income_research_pack -v
```

Expected: FAIL.

**Step 3: Implement minimal composition**

Do not add a new persistence layer. Just orchestrate existing primitives in parallel and produce an LLM-friendly summary block plus raw evidence blocks.

**Step 4: Run tests**

Run:
```bash
uv run pytest tests/test_fixed_income_use_cases.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add src/server/core/use_cases/fixed_income.py src/server/api/routes/fixed_income.py src/server/mcp/tools/fixed_income_tools.py tests/test_fixed_income_use_cases.py
git commit -m "feat: add fixed-income research pack"
```

---

### Task 8: Documentation and OpenAPI alignment

**Files:**
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\README.md`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\utils\openapi_generator.py`
- Modify: `C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\app.py`
- Test: existing smoke tests if any for docs/openapi mapping

**Step 1: Write failing lightweight assertions if project has OpenAPI mapping tests**

If no OpenAPI test exists, add a very small one that checks the fixed-income tag appears.

**Step 2: Implement docs updates**

Document:
- fixed-income tool group
- research-report integration requirement (`news-mcp` base URL)
- env vars
- recommended local run flow

**Step 3: Run tests**

Run:
```bash
uv run pytest tests/test_fixed_income_api.py tests/test_fixed_income_tools.py tests/test_response_contract.py -v
```

Expected: PASS.

**Step 4: Commit**

```bash
git add README.md src/server/utils/openapi_generator.py src/server/app.py tests/test_fixed_income_api.py tests/test_fixed_income_tools.py tests/test_response_contract.py
git commit -m "docs: document fixed-income and research integration"
```

---

## Testing strategy

### Unit tests

1. **Adapter normalization tests**
   - mock AkShare raw DataFrames
   - verify normalized output contracts for yield curves, option chains, Greeks, convertible bonds

2. **Client tests**
   - mock sibling REST responses
   - verify query mapping, timeout handling, disabled-mode behavior, normalization

3. **Use-case orchestration tests**
   - patch gateway/client methods
   - assert composite pack shape and error isolation

### API tests

Use the same app-construction pattern as `C:\Users\zheyu\Documents\dev\tools\stock-mcp\tests\test_sector_research.py:10-26`:
- patch `init_adapters`
- patch MCP creation if needed
- use FastAPI `TestClient`
- assert response envelope shapes via `response.json()["data"]`

### MCP tool tests

Mirror the style used in existing tool tests:
- call registration function into a test `FastMCP`
- invoke tool handlers directly or through registered interface
- verify markdown/json both work where applicable

### Integration tests

Add one optional integration-marked test that starts with `RESEARCH_REPORTS_BASE_URL` set to a local news-mcp instance and verifies end-to-end `/research/search` passthrough. Keep it behind an integration marker so normal CI stays deterministic.

### Verification commands

Run these before claiming completion:

```bash
uv run pytest tests/test_fixed_income_api.py tests/test_fixed_income_tools.py tests/test_fixed_income_use_cases.py tests/test_research_reports_client.py -v
uv run pytest -m "not integration"
uv run python -m py_compile src/server/app.py src/server/api/routes/fixed_income.py src/server/mcp/tools/fixed_income_tools.py src/server/infrastructure/clients/research_reports_client.py
```

---

## Tradeoffs

### Tradeoff 1: Dedicated fixed-income module vs leaving features in money-flow

**Recommended:** dedicated fixed-income module.

**Why:**
- `money_flow.py` already contains unrelated macro, margin, futures, bonds, and participant data (`C:\Users\zheyu\Documents\dev\tools\stock-mcp\src\server\api\routes\money_flow.py:138-599`).
- Leaving more bond/options work there increases discoverability problems for both developers and AI agents.
- A separate tool group makes “fixed-income research” a first-class capability.

### Tradeoff 2: REST client vs direct MySQL access

**Recommended:** REST client.

**Why:** cleaner ownership boundary, fewer runtime dependencies in stock-mcp, better long-term maintainability.

### Tradeoff 3: New service class vs use-case-only orchestration

**Recommended:** start with use-case-only orchestration, add `FixedIncomeService` only if formatting logic becomes bulky.

**Why:** aligns with YAGNI and current repo patterns where use-cases often wrap gateway methods directly.

### Tradeoff 4: Single composite feature first vs primitives first

**Recommended:** primitives first.

**Why:** composite AI features become much easier and safer once the normalized data contracts are stable.

---

## Notes for the implementer

- Preserve backward compatibility temporarily for old bond-related endpoints under money-flow, but make fixed-income the documented path.
- Do not duplicate news-mcp’s SQL or its full search grammar in stock-mcp.
- Keep public response shapes normalized and explicit; never leak raw AkShare column names as the long-term contract.
- Prefer JSON as the internal canonical contract, with markdown as a rendering layer for MCP convenience.
- Reuse existing artifact helpers in stock-mcp for MCP output consistency.
- Use `uv run python` and `uv run pytest` for all commands.

---

## Suggested MVP feature set

If scope needs tightening, the best MVP is:
1. normalized yield curve snapshot
2. stock option chain + Greeks + PCR summary
3. research-report search passthrough via news-mcp
4. one composite fixed-income research pack

Defer:
- direct credit spread datasets unless already easily available
- bond fundamental analytics beyond convertibles
- multi-provider fallback for research reports
- advanced volatility surface interpolation

---

Plan complete and saved to `docs/plans/2026-03-30-fixed-income-research-integration.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach?

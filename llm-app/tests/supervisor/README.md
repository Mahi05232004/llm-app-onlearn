# Supervisor Test Suite & Debug Panel

A multi-layered testing, tracing, and bug-capture system for the orchestrator.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [Test Suite](#test-suite)
   - [Unit Tests](#unit-tests)
   - [Integration Tests](#integration-tests)
   - [Scenario Tests](#scenario-tests)
4. [Debug Panel (UI)](#debug-panel-ui)
5. [Tracing System](#tracing-system)
6. [Bug Capture Workflow](#bug-capture-workflow)
7. [Test Utilities (Seed / Reset)](#test-utilities)
8. [API Reference](#api-reference)
9. [File Structure](#file-structure)

---

## Quick Start

### 1. Enable test endpoints

Already configured in `docker-compose.dev.yml` and `docker-compose.webpack.yml`:

```yaml
# llm-app service → environment
ENABLE_TEST_ENDPOINTS: "1"
```

This activates:
- Auto-tracing of every orchestrator turn (saved to MongoDB `traces` collection)
- 6 test API endpoints under `/api/test/`
- The debug panel at `http://localhost:3000/debug`

### 2. Start the stack

```bash
docker compose -f docker-compose.dev.yml up
```

### 3. Use the app

Chat normally. Every turn is automatically traced.

### 4. Open the Debug Panel

Navigate to **http://localhost:3000/debug** to view traces, flag bugs, and manage test users.

### 5. Run the automated tests

```bash
# ALL tests
docker compose exec llm-app uv run pytest tests/supervisor/ -v

# Unit tests only (fast, no DB, no LLM)
docker compose exec llm-app uv run pytest tests/supervisor/unit/ -v

# Integration tests only (mock agents, no LLM)
docker compose exec llm-app uv run pytest tests/supervisor/integration/ -v

# Captured scenario tests
docker compose exec llm-app uv run pytest tests/supervisor/scenarios/ -v
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        TESTING LAYERS                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐   ┌──────────────┐   ┌─────────────────────┐     │
│  │  Unit     │   │ Integration  │   │ Scenario Capture    │     │
│  │  Tests    │   │ Tests        │   │ (YAML replay)       │     │
│  │          │   │              │   │                     │     │
│  │ • router  │   │ • graph loop │   │ • flag in UI        │     │
│  │ • state   │   │ • handoffs   │   │ • export YAML       │     │
│  │ • planner │   │ • delegation │   │ • pytest replay     │     │
│  │ • tools   │   │ • max iter   │   │                     │     │
│  └──────────┘   └──────────────┘   └─────────────────────┘     │
│       ▲                ▲                     ▲                  │
│       │                │                     │                  │
│   conftest.py      mock agents         captured/*.yaml          │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                     RUNTIME TOOLS                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────────────┐    ┌───────────────────────────────┐     │
│  │ Debug Panel (UI)  │    │ Tracing System                │     │
│  │ localhost:3000     │    │                               │     │
│  │ /debug            │───▶│ TurnTracer → MongoDB traces   │     │
│  │                   │    │ Auto-records every turn        │     │
│  │ • View traces     │    │                               │     │
│  │ • Flag bugs       │    │ Endpoints:                    │     │
│  │ • Export YAML     │    │ • GET  /api/test/traces/{id}  │     │
│  │ • Seed/Reset      │    │ • POST /api/test/traces/flag  │     │
│  └───────────────────┘    └───────────────────────────────┘     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Test Suite

### Unit Tests

Located in `tests/supervisor/unit/`. These test individual functions in complete isolation — no DB, no LLM, no network.

| File | What it tests | Tests |
|---|---|---|
| `test_router.py` | `router()` and `post_agent_router()` — agent routing, mode switching, loop decisions | 12 |
| `test_state.py` | `merge_files()`, `_read_file_json()` — state helper functions | 15 |
| `test_plan_store.py` | `PlanStore` — MongoDB plan operations (mocked DB) | 5 |
| `test_planner_tools.py` | Planner tool creation and invocation (mocked service) | 4 |

**How they work:**
- All dependencies are mocked via `conftest.py` fixtures
- `mongomock` replaces real MongoDB
- Mock agent factories return deterministic responses
- Tests run in <1 second with zero external deps

```bash
# Run unit tests
docker compose exec llm-app uv run pytest tests/supervisor/unit/ -v

# Run a specific test file
docker compose exec llm-app uv run pytest tests/supervisor/unit/test_router.py -v

# Run a specific test
docker compose exec llm-app uv run pytest tests/supervisor/unit/test_router.py -v -k "test_router_default_master"
```

### Integration Tests

Located in `tests/supervisor/integration/`. These test the graph loop mechanics using **mock agents** — no real LLM calls.

| File | What it tests | Tests |
|---|---|---|
| `test_graph_loop.py` | Delegation, handback, loop continuation, max iteration cap, combined flows | 10 |

**How they work:**
- Mock agents simulate real agent behavior (returning routing updates, handoff calls, etc.)
- The graph's `router` → `agent` → `post_agent_router` loop is tested end-to-end
- Assertions verify: which agent was called, how many iterations ran, what routing state resulted

**Key scenarios covered:**
- ✅ No-loop: agent responds directly → `__end__`
- ✅ Handback loop: sub-agent → `hand_back_to_master` → master re-processes
- ✅ Delegation loop: master → `delegate_to_agent` → sub-agent → response
- ✅ Max iteration cap: loop stops at `MAX_ITERATIONS` even if `pending_handoff` is true
- ✅ Combined: handback + re-delegation in the same turn

```bash
docker compose exec llm-app uv run pytest tests/supervisor/integration/ -v
```

### Scenario Tests

Located in `tests/supervisor/scenarios/`. These replay **captured bugs** from real sessions.

**How they work:**
1. You encounter a bug while using the app
2. You flag it via the Debug Panel (or API)
3. The system exports a YAML file describing the state + expected behavior
4. The scenario runner loads the YAML and validates routing expectations

Scenario files live in `tests/supervisor/scenarios/captured/*.yaml`:

```yaml
name: should_delegate_after_handback
description: "Master should re-delegate after concept_tutor hands back"

setup:
  routing:
    active_agent: master
    handoff_summary: "Student completed Two Sum"
    handoff_reason: objective_complete
  mode: learn
  messages:
    - role: user
      content: "I solved it!"

expect:
  agent: concept_tutor
  tools_called: [request_plan_update]
  delegation_target: concept_tutor
  min_loop_iterations: 2
  comment: "Master should update plan and delegate to next topic"
```

```bash
docker compose exec llm-app uv run pytest tests/supervisor/scenarios/ -v
```

---

## Debug Panel (UI)

### Accessing

Open **http://localhost:3000/debug** in your browser.

### Tab 1: 📋 Traces

View every orchestrator turn for a given session.

**How to use:**
1. Copy a `sessionId` from your browser's network tab (look for the `/chat/stream` request body)
2. Paste it into the search box → click **Load Traces**
3. Each turn shows a summary row with:
   - Turn number
   - User's input message
   - Which agent handled it (badge)
   - Which tools were called (badge)
   - Whether it's flagged (🚩 badge)
4. **Click a row** to expand and see full details:
   - **Input**: message, mode, routing state before the turn
   - **Output**: agent name, tools called, iteration count, response preview, routing state after
5. Click **🚩 Flag as Bug** to open the flag dialog

### Tab 2: 🚩 Flagged

View all flagged turns across all sessions.

**How to use:**
1. Click the **🚩 Flagged** tab (auto-loads all flagged turns)
2. Expand any flagged turn to see the full trace + the expected behavior you wrote
3. Click **📤 Export as YAML Scenario** to generate a test case
4. A new window opens with the YAML — copy it and save to `tests/supervisor/scenarios/captured/<name>.yaml`

### Tab 3: 🛠 Tools

Quick utilities for test user management.

**How to use:**
1. Paste a MongoDB ObjectId into the User ID field
2. **🌱 Seed User + Plan** — Creates a test user with:
   - Pre-built student profile (intermediate, Python, DSA focus)
   - 3-week learning plan (9 topics: Arrays, Two Pointers, Binary Search)
   - Progress tracking initialized
   - Onboarding marked as complete (skips the guide flow)
3. **🔄 Reset (keep profile)** — Wipes plan, progress, and chat sessions but keeps the student profile so you don't re-onboard
4. **💣 Full Reset** — Wipes everything including profile (need to re-onboard)

Also includes a **Quick Reference** section with copy-paste test commands.

---

## Tracing System

### How it works

When `ENABLE_TEST_ENDPOINTS=1` is set:

1. **Every orchestrator streaming turn** is automatically recorded to the MongoDB `traces` collection
2. The tracing hook runs **after** the response is sent — it's fire-and-forget and cannot slow down or break the main flow
3. Each trace document contains:

```json
{
  "session_id": "abc123",
  "user_id": "user_object_id",
  "turn_index": 0,
  "timestamp": "2026-02-14T11:00:00Z",
  "input": {
    "message": "I solved it!",
    "mode": "learn",
    "routing": { "active_agent": "concept_tutor", "expected_mode": "learn" }
  },
  "output": {
    "messages": ["Great job! Let's move on to..."],
    "agent_name": "concept_tutor",
    "tools_called": ["hand_back_to_master"],
    "routing": { "active_agent": "master", "pending_handoff": true }
  },
  "iteration": 0,
  "duration_ms": 1234,
  "flagged": false,
  "flag_comment": "",
  "tags": []
}
```

### What gets traced

| Field | Source | Description |
|---|---|---|
| `session_id` | Request body | The chat session identifier |
| `user_id` | Request body | The user's MongoDB ObjectId |
| `input.message` | Request body | What the user typed |
| `input.mode` | Request body | `learn` or `code` |
| `input.routing` | State before turn | Routing state going in (active_agent, expected_mode, etc.) |
| `output.agent_name` | Final state | Which agent produced the last response |
| `output.tools_called` | Response scan | Tools detected in the response (delegate, handback, plan_update) |
| `output.routing` | Final state | Routing state after the turn |

### Safety guarantees

- **Cannot break the app**: The entire tracing block is wrapped in `try/except` — if MongoDB is down or tracing fails, the orchestrator continues normally
- **No performance impact**: Runs after the streaming response is sent
- **Only when enabled**: Gated behind `ENABLE_TEST_ENDPOINTS=1`; in production, zero tracing code is loaded

---

## Bug Capture Workflow

The full workflow from bug discovery to permanent test:

```
 ① Use the app normally
        │
        ▼
 ② Spot a wrong behavior
        │
        ▼
 ③ Open Debug Panel → Traces tab
    Find the turn → click "🚩 Flag as Bug"
    Write what SHOULD have happened
        │
        ▼
 ④ Go to Flagged tab
    Expand the flagged turn → "📤 Export as YAML Scenario"
        │
        ▼
 ⑤ Save the YAML to:
    tests/supervisor/scenarios/captured/<name>.yaml
        │
        ▼
 ⑥ Edit the `expect` section if needed
        │
        ▼
 ⑦ Run: docker compose exec llm-app uv run pytest tests/supervisor/scenarios/ -v
        │
        ▼
 ⑧ Fix the bug → test passes → committed as a regression guard
```

### Tips

- **Be specific in expected behavior**: "Should have delegated to concept_tutor after seeing objective_complete handback" is better than "wrong agent"
- **Use tags**: Tags like `routing`, `handoff`, `loop`, `plan` help categorize bugs
- **Check routing state**: The most common bugs are routing issues — look at `routing_before` vs `routing_after` in the trace to understand what went wrong

---

## Test Utilities

### Seed User

Creates a test user with pre-built data so you can test agent behavior without going through onboarding.

**Via Debug Panel:** Tools tab → paste ObjectId → click 🌱 Seed User + Plan

**Via API:**
```bash
curl -X POST http://localhost:8000/api/test/seed-user \
  -H "Content-Type: application/json" \
  -d '{"user_id": "OBJECT_ID", "with_plan": true, "with_progress": true}'
```

**What it creates:**
- Student profile: intermediate level, Python, DSA for interviews, 10 hrs/week
- 3-week plan with 9 topics (Two Sum, Valid Anagram, Group Anagrams, etc.)
- Progress tracking at 0%
- `isOnboarded: true` (skips the guide agent)

### Reset User

Wipes plan/progress/chat data so you can re-test from scratch.

**Via Debug Panel:** Tools tab → paste ObjectId → click 🔄 Reset or 💣 Full Reset

**Via API:**
```bash
# Keep profile (skip re-onboarding)
curl -X POST http://localhost:8000/api/test/reset-user \
  -H "Content-Type: application/json" \
  -d '{"user_id": "OBJECT_ID", "keep_profile": true}'

# Full reset (need to re-onboard)
curl -X POST http://localhost:8000/api/test/reset-user \
  -H "Content-Type: application/json" \
  -d '{"user_id": "OBJECT_ID", "keep_profile": false}'
```

---

## API Reference

All endpoints live under `/api/test/` and require `ENABLE_TEST_ENDPOINTS=1`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/test/traces/{session_id}` | Get all turns for a session |
| `GET` | `/api/test/traces/flagged` | Get all flagged turns |
| `POST` | `/api/test/traces/flag` | Flag a turn as a bug |
| `POST` | `/api/test/traces/export-scenario` | Export a flagged turn as YAML |
| `POST` | `/api/test/seed-user` | Create/update a test user with plan |
| `POST` | `/api/test/reset-user` | Reset user data |

You can also explore these interactively at **http://localhost:8000/docs** (FastAPI Swagger UI) — look for the `test` tag.

---

## File Structure

```
tests/supervisor/
├── __init__.py
├── conftest.py                         # Shared fixtures (mock agents, factories)
│
├── unit/
│   ├── __init__.py
│   ├── test_router.py                  # Router logic tests (12 tests)
│   ├── test_state.py                   # State helpers tests (15 tests)
│   ├── test_plan_store.py              # PlanStore tests (5 tests)
│   └── test_planner_tools.py           # Planner tools tests (4 tests)
│
├── integration/
│   ├── __init__.py
│   └── test_graph_loop.py              # Graph loop mechanics (10 tests)
│
├── scenarios/
│   ├── __init__.py
│   ├── runner.py                       # YAML scenario replay runner
│   ├── README.md                       # Scenario-specific docs
│   └── captured/
│       └── example_handback_delegation.yaml  # Example scenario
│
└── tracing/
    ├── __init__.py
    ├── tracer.py                       # TurnTracer (records to MongoDB)
    └── endpoints.py                    # 6 FastAPI test endpoints

web-app/app/
├── debug/
│   └── page.tsx                        # Debug Panel UI
└── api/debug/
    └── route.ts                        # API proxy to LLM backend
```

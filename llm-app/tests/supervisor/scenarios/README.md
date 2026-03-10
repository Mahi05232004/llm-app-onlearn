# Scenario Capture & Replay

> For the full testing documentation, see the [main README](../README.md).

This directory contains **captured bug scenarios** as YAML files. Each scenario represents a real bug observed during manual testing, converted into a reproducible test.

## Quick Start

```bash
# Run all scenarios
docker compose exec llm-app uv run pytest tests/supervisor/scenarios/ -v

# Run a specific one
docker compose exec llm-app uv run pytest tests/supervisor/scenarios/runner.py -v -k "handback"
```

## Capturing a Bug (via Debug Panel)

1. Open **http://localhost:3000/debug**
2. Load traces for your session → expand the broken turn
3. Click **🚩 Flag as Bug** → describe what should have happened
4. Go to **Flagged** tab → click **📤 Export as YAML Scenario**
5. Save the YAML to `tests/supervisor/scenarios/captured/<name>.yaml`
6. Edit the `expect` section → run `pytest`

## YAML Format

```yaml
name: descriptive_scenario_name
description: "What went wrong"

setup:
  mode: learn
  routing:
    active_agent: concept_tutor
    expected_mode: learn
    objective: "Teach Binary Search"
    question_id: "binary-search"
  files:
    /student_profile.json:
      content: '{"language": "Python", "experience": "intermediate"}'
      metadata: { type: json }
    /topic.json:
      content: '{"topic_id": "binary-search"}'
      metadata: { type: json }
  messages:
    - { role: assistant, content: "Let me explain..." }
    - { role: user, content: "One more example" }
  user_id: "test_user_123"

actual:
  agent: concept_tutor
  tools_called: [hand_back_to_master]
  tool_events:
    - { tool: hand_back_to_master, output_preview: '{"action":"hand_back_to_master",...}' }
  routing_after:
    active_agent: master
    pending_handoff: true
  response: "Here's another example..."

expect:
  comment: "Should NOT hand back — student asked for more examples"
  initial_agent: concept_tutor      # Level 1: which agent router should pick
  has_handoff: false                 # Level 2: should pending_handoff be set?
  routing_after:                     # Level 2: expected routing state after
    active_agent: concept_tutor
```

## Test Levels

| Level | What it tests | Speed | Requires |
|---|---|---|---|
| **1: Router** | Which agent the router picks for a given state | Fast, sync | `initial_agent` in expect |
| **2: Node replay** | Run through real node wrapper with mock agent | Async | `has_handoff` or `routing_after` in expect |

Both levels use **mock agents** — no real LLM calls. The `actual` section's response is fed to the mock agent, and the node wrapper's routing/handoff behavior is verified.

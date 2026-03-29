"""Export traces from MongoDB to local JSON files.

Usage:
    # Export all traces from the last 24 hours
    python -m tests.agentic.evals.export

    # Export a specific session
    python -m tests.agentic.evals.export --session sess_abc123

    # Export all flagged traces
    python -m tests.agentic.evals.export --flagged

    # Export with custom output dir
    python -m tests.agentic.evals.export --output tests/agentic/traces/raw
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, UTC, timedelta
from pathlib import Path

# Ensure llm-app root is on the path
_LLM_APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _LLM_APP_ROOT not in sys.path:
    sys.path.insert(0, _LLM_APP_ROOT)

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = os.path.join(_LLM_APP_ROOT, "tests", "agentic", "traces", "raw")


def _serialise_doc(doc: dict) -> dict:
    """Make a MongoDB document JSON-serialisable."""
    result = {}
    for key, value in doc.items():
        if key == "_id":
            result["_id"] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, dict):
            result[key] = _serialise_doc(value)
        elif isinstance(value, list):
            result[key] = [
                _serialise_doc(v) if isinstance(v, dict) else
                v.isoformat() if isinstance(v, datetime) else
                str(v) if hasattr(v, '__str__') and not isinstance(v, (str, int, float, bool, type(None))) else
                v
                for v in value
            ]
        else:
            result[key] = value
    return result


def _build_trace_file(doc: dict) -> dict:
    """Transform a MongoDB trace document into the local trace file format."""
    input_data = doc.get("input", {})
    output_data = doc.get("output", {})

    return {
        "meta": {
            "trace_id": doc.get("_id", ""),
            "session_id": doc.get("session_id", ""),
            "turn_index": doc.get("turn_index", 0),
            "module": doc.get("module", "dsa"),
            "mode": input_data.get("mode", "learn"),
            "thread_id": doc.get("thread_id", ""),
            "user_id": doc.get("user_id", ""),
            "timestamp": doc.get("timestamp", ""),
            "duration_ms": doc.get("duration_ms", 0),
        },
        "input": {
            "message": input_data.get("message", ""),
            "message_history": input_data.get("message_history", []),
            "tutor_context": input_data.get("tutor_context"),
            "store_before": input_data.get("store_before", input_data.get("store_snapshot", {})),
        },
        "output": {
            "response": output_data.get("response", ""),
            "agent_name": output_data.get("agent_name", ""),
            "tools_called": output_data.get("tools_called", []),
            "tool_events": output_data.get("tool_events", []),
            "suggestions": output_data.get("suggestions", []),
            "actions": output_data.get("actions", []),
            "scratchpad_updated": output_data.get("scratchpad_updated", False),
            "store_after": output_data.get("store_after", {}),
        },
        "annotation": doc.get("annotation"),
        "flagged": doc.get("flagged", False),
        "flag_comment": doc.get("flag_comment", ""),
        "tags": doc.get("tags", []),
    }


def export_session(session_id: str, output_dir: str) -> int:
    """Export all turns for a session to individual JSON files.

    Returns number of files written.
    """
    from tests.tracing.tracer import turn_tracer

    turns = turn_tracer.get_session_turns(session_id)
    if not turns:
        print(f"No turns found for session {session_id}")
        return 0

    session_dir = os.path.join(output_dir, session_id)
    os.makedirs(session_dir, exist_ok=True)

    count = 0
    for doc in turns:
        doc = _serialise_doc(doc)
        trace = _build_trace_file(doc)
        turn_idx = doc.get("turn_index", count)
        filepath = os.path.join(session_dir, f"turn_{turn_idx}.json")

        with open(filepath, "w") as f:
            json.dump(trace, f, indent=2, default=str)

        count += 1

    print(f"Exported {count} turns for session {session_id} → {session_dir}")
    return count


def export_recent(hours: int, output_dir: str) -> int:
    """Export all turns from the last N hours."""
    from tests.tracing.tracer import turn_tracer

    turns = turn_tracer.get_recent_turns(limit=200)
    if not turns:
        print("No recent turns found")
        return 0

    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    recent = [t for t in turns if t.get("timestamp", datetime.min) > cutoff]

    if not recent:
        print(f"No turns in the last {hours} hours")
        return 0

    # Group by session_id
    sessions: dict[str, list] = {}
    for doc in recent:
        sid = doc.get("session_id", "unknown")
        sessions.setdefault(sid, []).append(doc)

    total = 0
    for sid, docs in sessions.items():
        session_dir = os.path.join(output_dir, sid[:16])
        os.makedirs(session_dir, exist_ok=True)
        for doc in docs:
            doc = _serialise_doc(doc)
            trace = _build_trace_file(doc)
            turn_idx = doc.get("turn_index", total)
            filepath = os.path.join(session_dir, f"turn_{turn_idx}.json")
            with open(filepath, "w") as f:
                json.dump(trace, f, indent=2, default=str)
            total += 1

    print(f"Exported {total} turns from {len(sessions)} sessions → {output_dir}")
    return total


def export_flagged(output_dir: str) -> int:
    """Export all flagged turns to the annotated directory."""
    from tests.tracing.tracer import turn_tracer

    turns = turn_tracer.get_flagged_turns(limit=100)
    if not turns:
        print("No flagged turns found")
        return 0

    annotated_dir = os.path.join(os.path.dirname(output_dir), "annotated")
    os.makedirs(annotated_dir, exist_ok=True)

    count = 0
    for doc in turns:
        doc = _serialise_doc(doc)
        trace = _build_trace_file(doc)
        sid = doc.get("session_id", "unknown")[:8]
        turn_idx = doc.get("turn_index", count)
        filename = f"flagged_{sid}_turn{turn_idx}.json"
        filepath = os.path.join(annotated_dir, filename)

        with open(filepath, "w") as f:
            json.dump(trace, f, indent=2, default=str)

        count += 1

    print(f"Exported {count} flagged turns → {annotated_dir}")
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Export traces from MongoDB to local JSON files"
    )
    parser.add_argument(
        "--session", type=str, help="Export a specific session by ID"
    )
    parser.add_argument(
        "--flagged", action="store_true", help="Export all flagged turns"
    )
    parser.add_argument(
        "--hours", type=int, default=24,
        help="Export turns from the last N hours (default: 24)"
    )
    parser.add_argument(
        "--output", type=str, default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})"
    )

    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    if args.session:
        export_session(args.session, args.output)
    elif args.flagged:
        export_flagged(args.output)
    else:
        export_recent(args.hours, args.output)


if __name__ == "__main__":
    main()

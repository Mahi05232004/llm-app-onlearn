"""Eval Runner — orchestrates replay-based or trace-based evaluations.

Usage:
    # Replay flagged traces (deterministic replay + judge)
    python -m tests.agentic.evals.runner --replay -v

    # Filter by agent type
    python -m tests.agentic.evals.runner --replay --agent dsa -v

    # Replay from exported JSON files (offline)
    python -m tests.agentic.evals.runner --replay --from-json traces/flagged/ -v

    # Verbose output
    python -m tests.agentic.evals.runner --replay -v
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Ensure llm-app root is on the path
_LLM_APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _LLM_APP_ROOT not in sys.path:
    sys.path.insert(0, _LLM_APP_ROOT)

_REPORTS_DIR = os.path.join(_LLM_APP_ROOT, "tests", "agentic", "reports")


# ═══════════════════════════════════════════════════════════════════
# Report Generation
# ═══════════════════════════════════════════════════════════════════

def _generate_report(results: list[dict], output_dir: str) -> str:
    """Generate a markdown regression report.

    Returns the report file path.
    """
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(output_dir, f"eval_replay_{timestamp}.md")

    # Summary stats
    verdicts = [r["judge"]["verdict"] for r in results if "judge" in r]
    total = len(verdicts)
    fixed = verdicts.count("fixed")
    still_broken = verdicts.count("still_broken")
    regressed = verdicts.count("regressed")
    errors = verdicts.count("error")

    confidences = [
        r["judge"]["confidence"] for r in results
        if r.get("judge", {}).get("confidence")
    ]
    avg_confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.0

    lines = [
        f"# Eval Regression Report — {timestamp}",
        "",
        f"**Total flagged traces evaluated:** {total}",
        f"**Average judge confidence:** {avg_confidence}",
        "",
        "| Verdict | Count | % |",
        "|---------|-------|---|",
        f"| ✅ Fixed | {fixed} | {fixed*100//max(total,1)}% |",
        f"| 🔴 Still broken | {still_broken} | {still_broken*100//max(total,1)}% |",
        f"| ⚠️ Regressed | {regressed} | {regressed*100//max(total,1)}% |",
        f"| ❌ Error | {errors} | {errors*100//max(total,1)}% |",
        "",
        "---",
        "",
    ]

    for i, r in enumerate(results):
        replay = r.get("replay", {})
        judge = r.get("judge", {})
        meta = replay.get("meta", {})

        # Header
        sid = meta.get("session_id", "unknown")[:12]
        turn = meta.get("turn_index", "?")
        agent = meta.get("agent_type", "?")
        lines.append(f"## {i+1}. {sid} / turn {turn} ({agent})")
        lines.append(f"**Mode:** {meta.get('mode', '?')} | **Module:** {meta.get('module', '?')}")
        lines.append("")

        # Flag comment
        flag_comment = replay.get("flag_comment", "")
        if flag_comment:
            lines.append(f"**🚩 Feedback:** {flag_comment}")
            lines.append("")

        # Original vs new response (truncated)
        original = replay.get("original_response", "")
        new = replay.get("new_response", "")
        if original:
            lines.append(f"**Original response:** {original[:300]}{'...' if len(original) > 300 else ''}")
        if new:
            lines.append(f"**New response:** {new[:300]}{'...' if len(new) > 300 else ''}")
        lines.append("")

        # Verdict
        verdict = judge.get("verdict", "?")
        confidence = judge.get("confidence", 0)
        emoji = {"fixed": "✅", "still_broken": "🔴", "regressed": "⚠️", "error": "❌"}.get(verdict, "❓")
        lines.append(f"**Verdict:** {emoji} {verdict} (confidence: {confidence})")

        # Reasoning
        reasoning = judge.get("reasoning", "")
        if reasoning:
            lines.append(f"**Reasoning:** {reasoning}")

        # Details
        details = judge.get("details", {})
        if details:
            lines.append(f"**Addresses feedback:** {'✅' if details.get('addresses_feedback') else '❌'}")
            lines.append(f"**Quality vs original:** {details.get('quality_vs_original', '?')}")
            improvement = details.get("specific_improvement", "")
            if improvement:
                lines.append(f"**Improvement:** {improvement}")

        # Duration
        duration = replay.get("duration_ms", 0)
        if duration:
            lines.append(f"**Replay duration:** {duration}ms")

        lines.append("")
        lines.append("---")
        lines.append("")

    with open(report_path, "w") as f:
        f.write("\n".join(lines))

    return report_path


# ═══════════════════════════════════════════════════════════════════
# Replay Eval Pipeline
# ═══════════════════════════════════════════════════════════════════

async def run_replay_eval(
    agent_type: str | None = None,
    from_json: str = "",
    verbose: bool = False,
) -> dict[str, Any]:
    """Run replay-based eval: pull flagged traces → replay → judge → report."""
    from tests.agentic.evals.judge import Judge
    from tests.agentic.evals.replay_runner import (
        load_flagged_traces,
        load_traces_from_json,
        replay_trace,
    )

    # Load traces
    print("📋 Loading flagged traces...")
    if from_json:
        traces = load_traces_from_json(from_json)
    else:
        traces = load_flagged_traces(agent_type=agent_type)

    if not traces:
        print("No flagged traces found. Flag some traces in the staging UI first.")
        return {"total": 0, "results": []}

    print(f"🔄 Replaying {len(traces)} flagged traces (deterministic replay)...")
    judge = Judge()
    results = []

    for i, trace in enumerate(traces):
        sid = trace.get("session_id", "?")[:12]
        turn = trace.get("turn_index", "?")

        if verbose:
            print(f"  [{i+1}/{len(traces)}] {sid}/turn_{turn}...", end=" ", flush=True)

        # Replay
        replay_result = await replay_trace(trace)

        # Check for error
        if replay_result["new_response"].startswith("[ERROR]"):
            if verbose:
                print(f"❌ {replay_result['new_response']}")
            results.append({
                "replay": replay_result,
                "judge": {"verdict": "error", "reasoning": replay_result["new_response"], "confidence": 0.0, "details": {}},
            })
            continue

        # Judge
        judge_result = judge.score(replay_result)

        if verbose:
            verdict = judge_result.get("verdict", "?")
            confidence = judge_result.get("confidence", 0)
            emoji = {"fixed": "✅", "still_broken": "🔴", "regressed": "⚠️"}.get(verdict, "❓")
            print(f"{emoji} {verdict} (conf: {confidence}) [{replay_result.get('duration_ms', 0)}ms]")

        results.append({"replay": replay_result, "judge": judge_result})

    # Generate report
    report_path = _generate_report(results, _REPORTS_DIR)

    # Summary
    verdicts = [r["judge"]["verdict"] for r in results]
    fixed = verdicts.count("fixed")
    still_broken = verdicts.count("still_broken")
    regressed = verdicts.count("regressed")
    errors = verdicts.count("error")

    print(f"\n📊 Results: {fixed} fixed, {still_broken} still broken, {regressed} regressed, {errors} errors")
    print(f"📈 Fix rate: {fixed*100//max(len(results),1)}%")
    print(f"📄 Report: {report_path}")

    return {
        "total": len(results),
        "fixed": fixed,
        "still_broken": still_broken,
        "regressed": regressed,
        "errors": errors,
        "report_path": report_path,
        "results": results,
    }


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Run tutor agent evals (replay flagged traces)"
    )
    parser.add_argument(
        "--replay", action="store_true",
        help="Replay flagged traces (deterministic replay + judge)"
    )
    parser.add_argument(
        "--agent", type=str, default=None,
        help="Filter by agent type (dsa, ds, onboarding)"
    )
    parser.add_argument(
        "--from-json", type=str, default="",
        help="Load traces from JSON directory instead of MongoDB"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.replay:
        asyncio.run(run_replay_eval(
            agent_type=args.agent,
            from_json=args.from_json,
            verbose=args.verbose,
        ))
    else:
        print("Usage: python -m tests.agentic.evals.runner --replay -v")
        print("  --agent dsa|ds|onboarding  Filter by agent type")
        print("  --from-json DIR            Load from JSON instead of MongoDB")


if __name__ == "__main__":
    main()

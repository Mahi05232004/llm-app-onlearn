"""
Eval Case Manager — manages the permanent eval_cases and eval_runs collections.

Separates flagging/evaluation concerns from ephemeral trace storage.

Collections:
  - eval_cases: Permanent golden dataset of flagged traces (copied from traces)
  - eval_runs:  Historical eval run results

Usage:
    from tests.tracing.eval_store import eval_case_manager

    # Flag a trace (copy from traces → eval_cases)
    case_id = eval_case_manager.flag_trace(trace_id, "Should ask Socratic question", ["routing"])

    # Get all pending eval cases
    cases = eval_case_manager.get_eval_cases(status="pending")

    # Record an eval run
    eval_case_manager.record_eval_run(results, summary)
"""

import logging
from datetime import datetime, UTC
from typing import Any, Optional

logger = logging.getLogger(__name__)

MAX_MESSAGE_HISTORY = 20  # Cap history length when copying to eval_cases


class EvalCaseManager:
    """Manages eval_cases and eval_runs collections."""

    CASES_COLLECTION = "eval_cases"
    RUNS_COLLECTION = "eval_runs"

    def __init__(self):
        self._cases_col = None
        self._runs_col = None

    # ── Collection Init ──────────────────────────

    def _get_cases_collection(self):
        """Lazy-init the eval_cases collection."""
        if self._cases_col is None:
            try:
                from core.mongo_db import MongoDatabaseManager
                db = MongoDatabaseManager().get_database()
                self._cases_col = db[self.CASES_COLLECTION]
                # Unique index: one eval case per source trace
                self._cases_col.create_index("source_trace_id", unique=True, sparse=True)
                self._cases_col.create_index("status")
                self._cases_col.create_index("agent_type")
                self._cases_col.create_index("created_at")
            except Exception as e:
                logger.warning(f"EvalCaseManager: Could not connect to MongoDB: {e}")
                return None
        return self._cases_col

    def _get_runs_collection(self):
        """Lazy-init the eval_runs collection."""
        if self._runs_col is None:
            try:
                from core.mongo_db import MongoDatabaseManager
                db = MongoDatabaseManager().get_database()
                self._runs_col = db[self.RUNS_COLLECTION]
                self._runs_col.create_index("created_at")
            except Exception as e:
                logger.warning(f"EvalCaseManager: Could not connect to eval_runs: {e}")
                return None
        return self._runs_col

    # ── Flagging (copies trace → eval_cases) ─────

    def flag_trace(
        self,
        trace_id: str,
        expected_behavior: str,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Flag a trace by its _id — copies the full trace into eval_cases.

        Returns:
            {"status": "flagged", "case_id": "..."} on success.
            {"status": "error", "detail": "..."} on failure.
        """
        from bson import ObjectId

        cases_col = self._get_cases_collection()
        if cases_col is None:
            return {"status": "error", "detail": "MongoDB not available"}

        # Get the traces collection to read the source trace
        try:
            from core.mongo_db import MongoDatabaseManager
            db = MongoDatabaseManager().get_database()
            traces_col = db["traces"]
        except Exception as e:
            return {"status": "error", "detail": f"Cannot access traces: {e}"}

        # Parse trace_id
        try:
            obj_id = ObjectId(trace_id)
        except Exception:
            return {"status": "error", "detail": f"Invalid trace_id: {trace_id}"}

        # Read the source trace
        trace = traces_col.find_one({"_id": obj_id})
        if trace is None:
            return {
                "status": "error",
                "detail": "Trace not found. It may have expired (traces are kept for 7 days).",
            }

        # Validate the trace has real data
        input_data = trace.get("input", {})
        if not input_data or not input_data.get("message"):
            return {
                "status": "error",
                "detail": "Cannot flag a trace with no user message.",
            }

        if not expected_behavior.strip():
            return {"status": "error", "detail": "Flag comment cannot be empty."}

        # Check for duplicate
        existing = cases_col.find_one({"source_trace_id": str(obj_id)})
        if existing:
            return {
                "status": "duplicate",
                "detail": "This trace is already flagged.",
                "case_id": str(existing["_id"]),
            }

        # Build the eval case document (full snapshot)
        now = datetime.now(UTC)
        message_history = input_data.get("message_history", [])
        if len(message_history) > MAX_MESSAGE_HISTORY:
            message_history = message_history[-MAX_MESSAGE_HISTORY:]

        eval_case = {
            "source_trace_id": str(obj_id),
            "session_id": trace.get("session_id", ""),
            "user_id": trace.get("user_id", ""),
            "turn_index": trace.get("turn_index", 0),
            "thread_id": trace.get("thread_id", ""),
            "module": trace.get("module", "dsa"),
            "agent_type": trace.get("agent_type", "dsa"),
            # Full input snapshot
            "input": {
                "message": input_data.get("message", ""),
                "mode": input_data.get("mode", "learn"),
                "routing": input_data.get("routing", {}),
                "files": input_data.get("files", {}),
                "message_history": message_history,
                "tutor_context": input_data.get("tutor_context"),
                "store_before": input_data.get("store_before", {}),
            },
            # Full output snapshot
            "output": trace.get("output", {}),
            # Flag metadata
            "flag_comment": expected_behavior.strip(),
            "tags": tags or [],
            "status": "pending",  # pending → fixed | wont_fix
            # Timestamps
            "created_at": now,
            "flagged_at": now,
            "original_timestamp": trace.get("timestamp"),
        }

        try:
            result = cases_col.insert_one(eval_case)
            logger.info(f"Flagged trace {trace_id} → eval_case {result.inserted_id}")
            return {"status": "flagged", "case_id": str(result.inserted_id)}
        except Exception as e:
            if "duplicate key" in str(e).lower():
                return {"status": "duplicate", "detail": "This trace is already flagged."}
            logger.error(f"Failed to create eval case: {e}")
            return {"status": "error", "detail": f"Failed to save eval case: {e}"}

    def flag_by_session(
        self,
        session_id: str,
        turn_index: int,
        expected_behavior: str,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fallback: flag by session_id + turn_index (looks up trace first, then copies).

        Used when the frontend doesn't have a trace_id.
        NEVER creates a stub — if no trace exists, returns an error.
        """
        try:
            from core.mongo_db import MongoDatabaseManager
            db = MongoDatabaseManager().get_database()
            traces_col = db["traces"]
        except Exception as e:
            return {"status": "error", "detail": f"Cannot access traces: {e}"}

        trace = traces_col.find_one(
            {"session_id": session_id, "turn_index": turn_index}
        )
        if trace is None:
            return {
                "status": "error",
                "detail": f"No trace found for session {session_id}, turn {turn_index}. "
                          f"The trace may have expired.",
            }

        return self.flag_trace(
            trace_id=str(trace["_id"]),
            expected_behavior=expected_behavior,
            tags=tags,
        )

    def create_manual_case(
        self,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        flag_comment: str,
        tags: list[str] | None = None,
        agent_type: str = "plan_generator",
        module: str = "dsa",
        session_id: str = "",
        user_id: str = "",
    ) -> dict[str, Any]:
        """Create an eval case directly without a source trace.

        Used for plan-review flags and other flows that don't go through
        the chat orchestrator.
        """
        cases_col = self._get_cases_collection()
        if cases_col is None:
            return {"status": "error", "detail": "MongoDB not available"}

        if not flag_comment.strip():
            return {"status": "error", "detail": "Flag comment cannot be empty."}

        now = datetime.now(UTC)
        eval_case = {
            "source_trace_id": None,  # No source trace
            "session_id": session_id,
            "user_id": user_id,
            "turn_index": 0,
            "thread_id": "",
            "module": module,
            "agent_type": agent_type,
            "input": input_data,
            "output": output_data,
            "flag_comment": flag_comment.strip(),
            "tags": tags or [],
            "status": "pending",
            "created_at": now,
            "flagged_at": now,
            "original_timestamp": now,
        }

        try:
            result = cases_col.insert_one(eval_case)
            return {"status": "flagged", "case_id": str(result.inserted_id)}
        except Exception as e:
            return {"status": "error", "detail": f"Failed to save eval case: {e}"}

    # ── Querying ─────────────────────────────────

    def get_eval_cases(
        self,
        status: str | None = None,
        agent_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get eval cases, optionally filtered by status and agent_type."""
        cases_col = self._get_cases_collection()
        if cases_col is None:
            return []

        query: dict[str, Any] = {}
        if status:
            query["status"] = status
        if agent_type:
            query["agent_type"] = agent_type

        try:
            return list(
                cases_col.find(query)
                .sort("created_at", -1)
                .limit(limit)
            )
        except Exception as e:
            logger.warning(f"Failed to get eval cases: {e}")
            return []

    def get_eval_case_by_id(self, case_id: str) -> dict | None:
        """Get a single eval case by its _id."""
        from bson import ObjectId
        cases_col = self._get_cases_collection()
        if cases_col is None:
            return None
        try:
            return cases_col.find_one({"_id": ObjectId(case_id)})
        except Exception:
            return None

    def delete_eval_case(self, case_id: str) -> bool:
        """Delete an eval case by its _id."""
        from bson import ObjectId
        cases_col = self._get_cases_collection()
        if cases_col is None:
            return False
        try:
            result = cases_col.delete_one({"_id": ObjectId(case_id)})
            return result.deleted_count > 0
        except Exception as e:
            logger.warning(f"Failed to delete eval case: {e}")
            return False

    def delete_eval_case_by_session(self, session_id: str, turn_index: int) -> bool:
        """Delete an eval case by session_id + turn_index (backward compat)."""
        cases_col = self._get_cases_collection()
        if cases_col is None:
            return False
        try:
            result = cases_col.delete_one(
                {"session_id": session_id, "turn_index": turn_index}
            )
            return result.deleted_count > 0
        except Exception as e:
            logger.warning(f"Failed to delete eval case: {e}")
            return False

    def update_case_status(self, case_id: str, status: str) -> bool:
        """Update the status of an eval case (pending → fixed | wont_fix)."""
        from bson import ObjectId
        if status not in ("pending", "fixed", "wont_fix"):
            return False
        cases_col = self._get_cases_collection()
        if cases_col is None:
            return False
        try:
            result = cases_col.update_one(
                {"_id": ObjectId(case_id)},
                {"$set": {"status": status, "status_updated_at": datetime.now(UTC)}},
            )
            return result.modified_count > 0
        except Exception as e:
            logger.warning(f"Failed to update case status: {e}")
            return False

    # ── Eval Runs ────────────────────────────────

    def record_eval_run(
        self,
        results: list[dict],
        summary: dict[str, int],
    ) -> str | None:
        """Record an eval run with results and summary.

        Returns the run_id or None on failure.
        """
        import uuid
        runs_col = self._get_runs_collection()
        if runs_col is None:
            return None

        run_doc = {
            "run_id": str(uuid.uuid4()),
            "created_at": datetime.now(UTC),
            "summary": summary,
            "total_cases": len(results),
            "results": results,
        }

        try:
            result = runs_col.insert_one(run_doc)
            return run_doc["run_id"]
        except Exception as e:
            logger.warning(f"Failed to record eval run: {e}")
            return None

    def get_eval_runs(self, limit: int = 20) -> list[dict]:
        """Get recent eval runs."""
        runs_col = self._get_runs_collection()
        if runs_col is None:
            return []
        try:
            return list(
                runs_col.find({}, {"results": 0})  # Exclude full results for listing
                .sort("created_at", -1)
                .limit(limit)
            )
        except Exception as e:
            logger.warning(f"Failed to get eval runs: {e}")
            return []

    def get_eval_run(self, run_id: str) -> dict | None:
        """Get a single eval run by run_id (includes full results)."""
        runs_col = self._get_runs_collection()
        if runs_col is None:
            return None
        try:
            return runs_col.find_one({"run_id": run_id})
        except Exception:
            return None


# Singleton instance
eval_case_manager = EvalCaseManager()

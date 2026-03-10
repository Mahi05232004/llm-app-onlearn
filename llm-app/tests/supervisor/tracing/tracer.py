"""
Turn Tracer — Records orchestrator turns for scenario capture.

Stores rich, self-contained trace documents to MongoDB so that any
trace can be replayed or inspected independently.

Each trace captures:
  - Full input (message, mode, files, routing before)
  - Full output (response, agent, tools, routing after, files after)
  - Metadata (iteration count, duration, thread_id)
"""
import json
import logging
from datetime import datetime, UTC
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TurnTracer:
    """Records orchestrator turns to MongoDB for scenario capture."""

    COLLECTION_NAME = "traces"

    def __init__(self):
        self._collection = None

    def _get_collection(self):
        """Lazy-init the traces collection."""
        if self._collection is None:
            try:
                from core.mongo_db import MongoDatabaseManager
                db = MongoDatabaseManager().get_database()
                self._collection = db[self.COLLECTION_NAME]
                # Ensure useful indexes exist
                self._collection.create_index("session_id")
                self._collection.create_index("flagged")
                self._collection.create_index("timestamp")
                self._collection.create_index(
                    [("session_id", 1), ("turn_index", 1)], unique=True
                )
            except Exception as e:
                logger.warning(f"TurnTracer: Could not connect to MongoDB: {e}")
                return None
        return self._collection

    # ── helpers ──────────────────────────────────

    @staticmethod
    def _parse_routing(files: dict[str, Any]) -> dict:
        """Extract parsed routing JSON from a files dict."""
        routing_data = files.get("/routing.json", {})
        if isinstance(routing_data, dict):
            content = routing_data.get("content", "")
            if isinstance(content, str):
                try:
                    return json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    return {}
            elif isinstance(content, list):
                try:
                    return json.loads("\n".join(content))
                except (json.JSONDecodeError, TypeError):
                    return {}
        return {}

    @staticmethod
    def _serialise_files(files: dict[str, Any]) -> dict[str, Any]:
        """Make a files dict JSON-serialisable (lists→strings etc.)."""
        out: dict[str, Any] = {}
        for path, data in files.items():
            if isinstance(data, dict):
                content = data.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(str(line) for line in content)
                out[path] = {
                    "content": content,
                    "metadata": data.get("metadata", {}),
                }
            else:
                out[path] = str(data)
        return out

    def _next_turn_index(self, session_id: str) -> int:
        """Get the next turn_index for a session (auto-increment)."""
        collection = self._get_collection()
        if collection is None:
            return 0
        latest = collection.find_one(
            {"session_id": session_id},
            sort=[("turn_index", -1)],
            projection={"turn_index": 1},
        )
        if latest and "turn_index" in latest:
            return latest["turn_index"] + 1
        return 0

    # ── core API ─────────────────────────────────

    def record_turn(
        self,
        session_id: str,
        user_id: str,
        input_message: str,
        input_files: dict[str, Any],
        output_response: str,
        output_files: dict[str, Any],
        agent_name: str = "",
        tools_called: list[str] | None = None,
        tool_events: list[dict[str, Any]] | None = None,
        message_history: list[dict[str, str]] | None = None,
        iteration: int = 0,
        duration_ms: float = 0,
        thread_id: str = "",
        mode: str = "learn",
    ) -> Optional[str]:
        """Record a single orchestrator turn with full state snapshot.

        Returns the trace document ID, or None if tracing is unavailable.
        """
        collection = self._get_collection()
        if collection is None:
            return None

        routing_before = self._parse_routing(input_files)
        routing_after = self._parse_routing(output_files)
        turn_index = self._next_turn_index(session_id)

        doc = {
            "session_id": session_id,
            "user_id": user_id,
            "turn_index": turn_index,
            "thread_id": thread_id,
            "timestamp": datetime.now(UTC),
            # ── INPUT (everything needed to reproduce) ──
            "input": {
                "message": input_message,
                "mode": mode,
                "routing": routing_before,
                "files": self._serialise_files(input_files),
                "message_history": message_history or [],
            },
            # ── OUTPUT (what actually happened) ──
            "output": {
                "response": output_response,
                "agent_name": agent_name,
                "tools_called": tools_called or [],
                "tool_events": tool_events or [],
                "routing": routing_after,
                "files": self._serialise_files(output_files),
            },
            "iteration": iteration,
            "duration_ms": duration_ms,
            # ── flagging ──
            "flagged": False,
            "flag_comment": "",
            "tags": [],
        }

        try:
            result = collection.insert_one(doc)
            return str(result.inserted_id)
        except Exception as e:
            logger.warning(f"TurnTracer: Failed to record turn: {e}")
            return None

    def flag_turn(
        self,
        session_id: str,
        turn_index: int,
        expected_behavior: str,
        tags: list[str] | None = None,
    ) -> bool:
        """Flag a recorded turn as a bug with expected behavior."""
        collection = self._get_collection()
        if collection is None:
            return False

        try:
            result = collection.update_one(
                {"session_id": session_id, "turn_index": turn_index},
                {
                    "$set": {
                        "flagged": True,
                        "flag_comment": expected_behavior,
                        "flagged_at": datetime.now(UTC),
                    },
                    "$addToSet": {"tags": {"$each": tags or []}},
                },
            )
            return result.modified_count > 0
        except Exception as e:
            logger.warning(f"TurnTracer: Failed to flag turn: {e}")
            return False

    def get_flagged_turns(
        self,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get all flagged turns, optionally filtered by session."""
        collection = self._get_collection()
        if collection is None:
            return []

        query: dict[str, Any] = {"flagged": True}
        if session_id:
            query["session_id"] = session_id

        try:
            return list(collection.find(query).sort("timestamp", -1).limit(limit))
        except Exception as e:
            logger.warning(f"TurnTracer: Failed to get flagged turns: {e}")
            return []

    def get_session_turns(self, session_id: str) -> list[dict]:
        """Get all turns for a session, ordered by turn_index."""
        collection = self._get_collection()
        if collection is None:
            return []

        try:
            return list(
                collection.find({"session_id": session_id}).sort("turn_index", 1)
            )
        except Exception as e:
            logger.warning(f"TurnTracer: Failed to get session turns: {e}")
            return []

    def get_recent_turns(self, limit: int = 30) -> list[dict]:
        """Get the most recent turns across all sessions."""
        collection = self._get_collection()
        if collection is None:
            return []

        try:
            return list(collection.find().sort("timestamp", -1).limit(limit))
        except Exception as e:
            logger.warning(f"TurnTracer: Failed to get recent turns: {e}")
            return []


# Singleton instance
turn_tracer = TurnTracer()

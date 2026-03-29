"""
MongoDB-backed LangGraph checkpointer for cross-session agent memory.

Uses the official langgraph-checkpoint-mongodb package which stores
checkpoints in a dedicated MongoDB collection (keyed by thread_id).

Thread ID format: dsa_{userId}
  → One persistent thread per user, spanning ALL chat sessions.
  → The agent remembers everything across questions/sessions.
"""

import logging
import os
from typing import Optional

from core.pruning_checkpointer import PruningMongoDBSaver
from pymongo import MongoClient

logger = logging.getLogger(__name__)


# ── Singleton instances ──────────────────────────────────────────────────
_checkpointer: Optional[PruningMongoDBSaver] = None
_mongo_client: Optional[MongoClient] = None


def get_checkpointer() -> PruningMongoDBSaver:
    """Get singleton MongoDB checkpointer instance.
    
    Uses the official MongoDBSaver from langgraph-checkpoint-mongodb.
    Stores checkpoints in the 'onlearn' database, 'agent_checkpoints' collection.
    Supports arbitrary thread_id formats (including our 'dsa_{userId}').
    """
    global _checkpointer, _mongo_client
    
    if _checkpointer is None:
        mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
        db_name = os.environ.get("MONGO_DB", "onlearn")
        
        _mongo_client = MongoClient(mongo_uri)
        _checkpointer = PruningMongoDBSaver(
            client=_mongo_client,
            db_name=db_name,
            max_checkpoints=5
        )
        logger.info(f"MongoDB checkpointer initialized (db={db_name})")
    
    return _checkpointer

"""
Custom LangGraph checkpointer that stores state in existing chatsessions collection.
Thread ID format: learn_{sessionId}, code_{sessionId}, or thread_{messageId}_{sessionId}

This provides a single source of truth - all checkpoint data is stored
within the existing chatsessions documents rather than separate collections.
"""
import logging
from typing import Any, Optional, Iterator, Tuple, Sequence

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langchain_core.runnables import RunnableConfig
from bson import ObjectId

from core.mongo_db import mongo_db_manager

logger = logging.getLogger(__name__)


class ChatSessionCheckpointer(BaseCheckpointSaver):
    """
    Stores LangGraph checkpoints directly in the chatsessions collection.
    
    Thread ID formats:
    - Main learn chat: "learn_{sessionId}"
    - Main code chat: "code_{sessionId}"  
    - Onboarding chat: "onboarding_{sessionId}"
    - Sub-threads (reply-in-thread): "thread_{messageId}_{sessionId}"
    
    Storage locations:
    - learn/code/onboarding: stored in session.langgraph_checkpoint_{mode}
    - sub-threads: stored in session.messages[].langgraph_checkpoint (on the parent message)
    """
    
    serde = JsonPlusSerializer()
    
    def __init__(self):
        super().__init__()
        self.db = mongo_db_manager.get_database()
        self.collection = self.db.chatsessions
        # Separate collection for checkpoints that can't be stored in chatsessions
        # (e.g., onboarding sessions with non-ObjectId session IDs)
        self.checkpoint_collection = self.db.langgraph_checkpoints
        logger.info("ChatSessionCheckpointer initialized")
    
    def _parse_thread_id(self, thread_id: str) -> Tuple[str, str, Optional[str]]:
        """
        Parse thread_id to get (type, id, session_id).
        Returns: (thread_type, primary_id, session_id or None)
        """
        if thread_id.startswith("learn_"):
            return "learn", thread_id[6:], None
        elif thread_id.startswith("code_"):
            return "code", thread_id[5:], None
        elif thread_id.startswith("onboarding_"):
            return "onboarding", thread_id[11:], None
        elif thread_id.startswith("thread_"):
            # Format: thread_{messageId}_{sessionId}
            parts = thread_id[7:].rsplit("_", 1)
            if len(parts) == 2:
                return "thread", parts[0], parts[1]  # messageId, sessionId
            return "thread", parts[0], None
        return "unknown", thread_id, None
    
    def _is_valid_objectid(self, value: str) -> bool:
        """Check if a string is a valid MongoDB ObjectId."""
        try:
            ObjectId(value)
            return True
        except Exception:
            return False
    
    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Save checkpoint to chatsessions collection."""
        thread_id = config["configurable"]["thread_id"]
        thread_type, primary_id, session_id = self._parse_thread_id(thread_id)
        
        checkpoint_id = checkpoint["id"]
        
        # Serialize checkpoint data using dumps_typed which returns (type, bytes)
        checkpoint_data = {
            "checkpoint": self.serde.dumps_typed(checkpoint),
            "metadata": self.serde.dumps_typed(metadata),
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
            "versions": self.serde.dumps_typed(new_versions),
        }
        
        try:
            if thread_type in ("learn", "code", "onboarding"):
                if self._is_valid_objectid(primary_id):
                    # Main chat / onboarding with valid ObjectId: store at session level
                    result = self.collection.update_one(
                        {"_id": ObjectId(primary_id)},
                        {"$set": {f"langgraph_checkpoint_{thread_type}": checkpoint_data}},
                        upsert=False
                    )
                    logger.debug(f"Saved checkpoint for {thread_type} mode, session {primary_id}, matched: {result.matched_count}")
                else:
                    # Non-ObjectId session ID (e.g., ds_ prefixed): store in separate collection
                    self.checkpoint_collection.update_one(
                        {"thread_id": thread_id},
                        {"$set": {"checkpoint_data": checkpoint_data, "thread_type": thread_type}},
                        upsert=True
                    )
                    logger.debug(f"Saved checkpoint for {thread_type} mode to checkpoints collection, thread {thread_id}")
                    
            elif thread_type == "thread" and session_id:
                # Sub-thread: store in the parent message's subdocument
                result = self.collection.update_one(
                    {"_id": ObjectId(session_id), "messages._id": ObjectId(primary_id)},
                    {"$set": {"messages.$.langgraph_checkpoint": checkpoint_data}},
                    upsert=False
                )
                logger.debug(f"Saved checkpoint for sub-thread, message {primary_id}, matched: {result.matched_count}")
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")
            raise
        
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }
    
    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Store intermediate writes for pending tasks.
        
        For now, we don't store intermediate writes separately since our 
        streaming use case primarily needs final checkpoints.
        """
        # TODO: Implement if needed for more complex interrupt/resume scenarios
        pass
    
    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Load checkpoint from chatsessions collection."""
        thread_id = config["configurable"]["thread_id"]
        thread_type, primary_id, session_id = self._parse_thread_id(thread_id)
        
        checkpoint_data = None
        
        try:
            if thread_type in ("learn", "code", "onboarding"):
                if self._is_valid_objectid(primary_id):
                    # Main chat / onboarding with valid ObjectId: fetch from session level
                    session = self.collection.find_one({"_id": ObjectId(primary_id)})
                    if session:
                        checkpoint_data = session.get(f"langgraph_checkpoint_{thread_type}")
                else:
                    # Non-ObjectId session ID: fetch from separate collection
                    doc = self.checkpoint_collection.find_one({"thread_id": thread_id})
                    if doc:
                        checkpoint_data = doc.get("checkpoint_data")
                    
            elif thread_type == "thread" and session_id:
                # Sub-thread: fetch from parent message
                session = self.collection.find_one(
                    {"_id": ObjectId(session_id), "messages._id": ObjectId(primary_id)},
                    {"messages.$": 1}
                )
                if session and session.get("messages"):
                    checkpoint_data = session["messages"][0].get("langgraph_checkpoint")
        except Exception as e:
            logger.error(f"Failed to get checkpoint: {e}")
            return None
        
        if not checkpoint_data:
            return None
        
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_data.get("checkpoint_id"),
                }
            },
            checkpoint=self.serde.loads_typed(tuple(checkpoint_data["checkpoint"])),
            metadata=self.serde.loads_typed(tuple(checkpoint_data["metadata"])),
            parent_config=None,  # We don't track parent checkpoints for simplicity
            pending_writes=[],
        )
    
    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """List checkpoints (returns single latest checkpoint per thread)."""
        if config is None:
            return
        
        result = self.get_tuple(config)
        if result:
            yield result

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Async save checkpoint (wraps sync put)."""
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Async save writes (wraps sync put_writes)."""
        return self.put_writes(config, writes, task_id)

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Async load checkpoint (wraps sync get_tuple)."""
        return self.get_tuple(config)

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """Async list checkpoints (wraps sync list)."""
        if config is None:
            return
        
        # Async generator wrapper
        result = self.get_tuple(config)
        if result:
            yield result


# Singleton instance
_checkpointer: Optional[ChatSessionCheckpointer] = None


def get_checkpointer() -> ChatSessionCheckpointer:
    """Get singleton checkpointer instance."""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = ChatSessionCheckpointer()
    return _checkpointer

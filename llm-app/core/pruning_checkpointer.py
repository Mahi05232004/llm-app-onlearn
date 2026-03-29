import asyncio
import logging
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata, ChannelVersions
from langgraph.checkpoint.mongodb.saver import MongoDBSaver

logger = logging.getLogger(__name__)


def _assert_no_mocks(obj, thread_id: str, _path: str = "checkpoint", _depth: int = 0) -> None:
    """Recursively scan a checkpoint for MagicMock instances before writing to MongoDB.

    LangGraph's MongoDBSaver has its own JsonPlusSerializer that handles LangChain
    types (HumanMessage, AIMessage, etc.) perfectly well. We should NOT call ormsgpack
    directly on the checkpoint — instead, we only need to catch test contamination
    where MagicMock objects have leaked into the state.
    """
    if _depth > 10:
        return  # Avoid infinite recursion on deeply nested state
    try:
        from unittest.mock import MagicMock
    except ImportError:
        MagicMock = None

    if MagicMock is not None and isinstance(obj, MagicMock):
        logger.error(
            "[Checkpointer] Refusing to write checkpoint with MagicMock at path '%s' "
            "for thread=%s. This is caused by test mocks leaking into production state.",
            _path, thread_id,
        )
        raise TypeError(
            f"Type is not serializable: MagicMock found at '{_path}' in checkpoint for "
            f"thread '{thread_id}'. A test mock has leaked into production state."
        )

    if isinstance(obj, dict):
        for k, v in obj.items():
            _assert_no_mocks(v, thread_id, f"{_path}.{k}", _depth + 1)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _assert_no_mocks(v, thread_id, f"{_path}[{i}]", _depth + 1)


class PruningMongoDBSaver(MongoDBSaver):
    """Wraps MongoDBSaver to asynchronously prune old checkpoints per thread to prevent O(N^2) DB bloat."""
    
    def __init__(self, *args, max_checkpoints: int = 5, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_checkpoints = max_checkpoints

    async def aput(self, config: RunnableConfig, checkpoint: Checkpoint, metadata: CheckpointMetadata, new_versions: ChannelVersions) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]

        # 0. Guard: catch MagicMock contamination before it corrupts MongoDB
        _assert_no_mocks(checkpoint, thread_id)

        # 1. Execute standard asynchronous write
        result = await super().aput(config, checkpoint, metadata, new_versions)
        
        # 2. Fire-and-forget background pruning task off the main event loop
        loop = asyncio.get_running_loop()
        loop.create_task(self._aprune_old_checkpoints(thread_id))
        return result

    def put(self, config: RunnableConfig, checkpoint: Checkpoint, metadata: CheckpointMetadata, new_versions: ChannelVersions) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]

        # 0. Guard: catch MagicMock contamination before it corrupts MongoDB
        _assert_no_mocks(checkpoint, thread_id)

        # 1. Execute standard synchronous write
        result = super().put(config, checkpoint, metadata, new_versions)
        
        # 2. Try to fire an async task if an event loop exists, else run synchronously
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._aprune_old_checkpoints(thread_id))
        except RuntimeError: # No active event loop
            self._prune_old_checkpoints(thread_id)
        return result

    def _prune_old_checkpoints(self, thread_id: str):
        """Finds the Nth most recent checkpoint and deletes everything older in the thread."""
        try:
            # Query MongoDB: sort descending by id (timestamp timestamp), skip the first N (e.g. 5)
            cursor = self.checkpoint_collection.find(
                {"thread_id": thread_id},
                {"checkpoint_id": 1, "_id": 0}
            ).sort("checkpoint_id", -1).skip(self.max_checkpoints).limit(1)
            
            docs = list(cursor)
            if not docs:
                return # Thread has fewer than max_checkpoints; no bloat exists yet
                
            cutoff_id = docs[0]["checkpoint_id"]
            
            # Atomic hard-deletes on both checkpointer collections using $lte bounds
            query = {
                "thread_id": thread_id,
                "checkpoint_id": {"$lte": cutoff_id}
            }
            c_result = self.checkpoint_collection.delete_many(query)
            w_result = self.writes_collection.delete_many(query)
            
            logger.debug(f"Pruned older checkpoints for thread_id={thread_id} at cutoff {cutoff_id}. Deleted {c_result.deleted_count} states.")
        except Exception as e:
            logger.error(f"Failed to prune checkpoints for thread {thread_id}: {e}")

    async def _aprune_old_checkpoints(self, thread_id: str):
        from langchain_core.runnables import run_in_executor
        await run_in_executor(None, self._prune_old_checkpoints, thread_id)

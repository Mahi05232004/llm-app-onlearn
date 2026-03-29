"""MongoDB-backed store factory for the Tutor agent."""

import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Optional, Union

from pymongo import DeleteOne, MongoClient, UpdateOne
from pymongo.errors import BulkWriteError

from langgraph.store.base import (
    GetOp,
    ListNamespacesOp,
    Op,
    PutOp,
    Result,
    SearchOp,
)
from langgraph.store.mongodb import MongoDBStore
from langchain_core.runnables import run_in_executor

from app.clients.llm_client import AzureLLMClient

logger = logging.getLogger(__name__)


class ResilientMongoDBStore(MongoDBStore):
    """MongoDBStore subclass that handles duplicate-key race conditions.
    
    Fast agentic models (e.g. Kimi-K2.5) may fire multiple parallel tool calls
    that simultaneously attempt to upsert the same key-value pair. The default
    MongoDBStore uses `bulk_write(ordered=True)`, which aborts on the first
    duplicate key error (E11000), crashing the entire agent turn.
    
    This subclass overrides `batch` to use `ordered=False`, which instructs
    MongoDB to continue processing remaining writes even if one fails with a
    duplicate key error. The result is that the last writer wins (correct for
    an upsert-based store), and the agent never crashes.
    """

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        results: list[Result] = []
        dedupped_putops: dict[tuple[tuple[str, ...], str], PutOp] = {}
        writes: list[Union[DeleteOne, UpdateOne]] = []

        for op in ops:
            if isinstance(op, PutOp):
                dedupped_putops[(op.namespace, op.key)] = op
                results.append(None)

            elif isinstance(op, GetOp):
                results.append(
                    self.get(
                        namespace=op.namespace,
                        key=op.key,
                        refresh_ttl=op.refresh_ttl,
                    )
                )

            elif isinstance(op, SearchOp):
                results.append(
                    self.search(
                        op.namespace_prefix,
                        query=op.query,
                        filter=op.filter,
                        limit=op.limit,
                        offset=op.offset,
                        refresh_ttl=op.refresh_ttl,
                    )
                )

            elif isinstance(op, ListNamespacesOp):
                prefix = None
                suffix = None
                if op.match_conditions:
                    for cond in op.match_conditions:
                        if cond.match_type == "prefix":
                            prefix = cond.path
                        elif cond.match_type == "suffix":
                            suffix = cond.path
                        else:
                            raise ValueError(
                                f"Match type {cond.match_type} must be prefix or suffix."
                            )
                results.append(
                    self.list_namespaces(
                        prefix=prefix,
                        suffix=suffix,
                        max_depth=op.max_depth,
                        limit=op.limit,
                        offset=op.offset,
                    )
                )

        if self.index_config:
            texts = self._extract_texts(list(dedupped_putops.values()))
            if not self._is_autoembedding:
                vectors = self.embeddings.embed_documents(texts)
            v = 0

        for op in dedupped_putops.values():
            if op.value is None:
                writes.append(
                    DeleteOne(filter={"namespace": list(op.namespace), "key": op.key})
                )
            else:
                to_set: dict[str, Any] = {
                    "value": op.value,
                    "updated_at": datetime.now(tz=timezone.utc),
                }
                if self.index_config:
                    embed = texts[v] if self._is_autoembedding else vectors[v]
                    to_set[self._embedding_key] = embed
                    to_set["namespace_prefix"] = self._denormalize_path(op.namespace)
                    v += 1

                writes.append(
                    UpdateOne(
                        filter={"namespace": list(op.namespace), "key": op.key},
                        update={
                            "$set": to_set,
                            "$setOnInsert": {
                                "created_at": datetime.now(tz=timezone.utc),
                            },
                        },
                        upsert=True,
                    )
                )

        if writes:
            try:
                # ordered=False: MongoDB continues processing all writes even if
                # one fails (e.g. E11000 duplicate key from a parallel upsert).
                # The last write wins, which is the correct behaviour for a store.
                self.collection.bulk_write(writes, ordered=False)
            except BulkWriteError as bwe:
                # Filter out duplicate-key errors (code 11000) — these are safe
                # to ignore for upsert operations. Any other error is re-raised.
                non_duplicate_errors = [
                    err for err in bwe.details.get("writeErrors", [])
                    if err.get("code") != 11000
                ]
                if non_duplicate_errors:
                    logger.error(
                        f"Non-duplicate BulkWriteError: {non_duplicate_errors}"
                    )
                    raise
                logger.debug(
                    f"Swallowed {len(bwe.details.get('writeErrors', []))} "
                    "duplicate-key errors from concurrent parallel tool calls."
                )

        return results

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        return await run_in_executor(None, self.batch, ops)


def create_tutor_store(
    mongo_uri: str,
    db_name: str = "onlearn",
    collection_name: str = "tutor_files",
) -> ResilientMongoDBStore:
    """Create a ResilientMongoDBStore for persistent file storage."""
    client = MongoClient(mongo_uri)
    collection = client[db_name][collection_name]

    # Initialize the high-performance Azure embedding model for Semantic RAG
    # text-embedding-3-large has 3072 dimensions
    llm_client = AzureLLMClient()
    embeddings = llm_client.get_embedding_model()

    # LangGraph will automatically embed any Document saved with index=True
    return ResilientMongoDBStore(
        collection=collection,
        index={"embed": embeddings, "dims": 3072}
    )


import os
_store_instance = None


def get_tutor_store() -> ResilientMongoDBStore:
    """Singleton accessor for the Tutor Store."""
    global _store_instance
    if _store_instance is None:
        mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
        _store_instance = create_tutor_store(mongo_uri)
    return _store_instance
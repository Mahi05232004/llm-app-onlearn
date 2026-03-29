import os
import logging
from pymongo import MongoClient
from dotenv import load_dotenv

# Try to load environment variables from the staging or dev files
load_dotenv(".env.staging")
load_dotenv(".env.dev")
load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate():
    mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.environ.get("MONGO_DB", "onlearn")
    logger.info(f"Connecting to MongoDB at {mongo_uri} database {db_name}")
    
    client = MongoClient(mongo_uri)
    db = client[db_name]
    checkpoints = db["checkpoints"]
    writes = db["checkpoint_writes"]
    
    threads = checkpoints.distinct("thread_id")
    logger.info(f"Found {len(threads)} unique threads.")
    
    deleted_checkpoints = 0
    deleted_writes = 0
    
    for thread_id in threads:
        # Sort descending by checkpoint_id, get the 6th document
        cursor = checkpoints.find(
            {"thread_id": thread_id}, 
            {"checkpoint_id": 1, "_id": 0}
        ).sort("checkpoint_id", -1).skip(5).limit(1)
        
        docs = list(cursor)
        if docs:
            cutoff_id = docs[0]["checkpoint_id"]
            
            # Delete anything older than or equal to cutoff_id
            query = {
                "thread_id": thread_id,
                "checkpoint_id": {"$lte": cutoff_id}
            }
            res_c = checkpoints.delete_many(query)
            res_w = writes.delete_many(query)
            
            deleted_checkpoints += res_c.deleted_count
            deleted_writes += res_w.deleted_count
            logger.info(f"Thread {thread_id}: Deleted {res_c.deleted_count} checkpoints and {res_w.deleted_count} writes.")
            
    logger.info("Migration Complete!")
    logger.info(f"Total Excessive Checkpoints Deleted: {deleted_checkpoints}")
    logger.info(f"Total Excessive Writes Deleted: {deleted_writes}")

if __name__ == "__main__":
    migrate()

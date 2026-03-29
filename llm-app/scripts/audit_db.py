import os
import logging
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv(".env.staging")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def audit():
    mongo_uri = os.environ.get("MONGO_URI")
    db_name = os.environ.get("MONGO_DB", "onlearn")
    client = MongoClient(mongo_uri)
    db = client[db_name]
    
    print(f"\nAudit for database: {db_name}")
    print("-" * 50)
    
    collections = db.list_collection_names()
    for coll_name in collections:
        stats = db.command("collstats", coll_name)
        count = stats.get("count", 0)
        size_mb = stats.get("size", 0) / (1024 * 1024)
        storage_mb = stats.get("storageSize", 0) / (1024 * 1024)
        avg_obj_size = stats.get("avgObjSize", 0)
        
        print(f"Collection: {coll_name}")
        print(f"  Count: {count} documents")
        print(f"  Size (Logical): {size_mb:.2f} MB")
        print(f"  Size (Storage): {storage_mb:.2f} MB")
        print(f"  Avg Doc Size: {avg_obj_size} bytes")
        
        if coll_name in ["checkpoints", "checkpoint_writes"]:
            # We know these collections just had a massive deletion event.
            # MongoDB does not automatically reclaim disk space. We must force compaction.
            print(f"  [!] Forcing storage compaction for {coll_name}...")
            try:
                db.command("compact", coll_name)
                print(f"  [✓] Compaction triggered successfully.")
            except Exception as e:
                # Atlas Shared tiers (M0/M2/M5) sometimes prohibit manual compact commands
                print(f"  [!] Compaction failed or prohibited by Atlas tier: {e}")
                
        print("-" * 50)

if __name__ == "__main__":
    audit()

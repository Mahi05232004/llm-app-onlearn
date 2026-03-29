import asyncio
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from app.tutor.core.store import get_tutor_store

import uuid

async def main():
    print("🧪 Debugging MongoDBStore Namespace Behavior")
    # Generate random collection to ensure clean state
    rand_coll = f"debug_{uuid.uuid4().hex[:6]}"
    print(f"Using collection: {rand_coll}")
    
    # We need to create a new store instance with this collection
    # Hack: Access the client from existing store or recreate
    from app.tutor.core.store import create_tutor_store
    import os
    mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    store = create_tutor_store(mongo_uri, collection_name=rand_coll)
    
    # Test 1: Insert check with STRING
    ns1 = "user1_string"
    key = "file.txt"
    print(f"Set 1: {ns1} (type {type(ns1)}) -> {key}")
    try:
        await store.aput(ns1, key, {"data": "user1"})
        print("✅ Insert 1 Success")
    except Exception as e:
        print(f"❌ Insert 1 Failed: {e}")
        
    # Test 2: Update check (Idempotency)
    print(f"Set 1 again (Update): {ns1} -> {key}")
    try:
        await store.aput(ns1, key, {"data": "user1_updated"})
        print("✅ Update 1 Success")
    except Exception as e:
        print(f"❌ Update 1 Failed: {e}")

    # Test 3: Insert Tuple check
    ns2 = ("user2_tuple",)
    print(f"Set 3: {ns2} (type {type(ns2)}) -> {key}")
    try:
        await store.aput(ns2, key, {"data": "user2"})
        print("✅ Insert 3 Success")
    except Exception as e:
        print(f"❌ Insert 3 Failed: {e}")
        
    # Test 4: Update Tuple check
    print(f"Set 3 again (Update): {ns2} -> {key}")
    try:
        await store.aput(ns2, key, {"data": "user2_updated"})
        print("✅ Update 3 Success")
    except Exception as e:
        print(f"❌ Update 3 Failed: {e}")

    # Inspect
    print("🔍 Listing items...")
    try:
        results = await store.asearch(ns1)
        print(f"Found for string ns: {len(results)}")
        results2 = await store.asearch(ns2)
        print(f"Found for tuple ns: {len(results2)}")
    except Exception as e:
        print(f"Search failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())

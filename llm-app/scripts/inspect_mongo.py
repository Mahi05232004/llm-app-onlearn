import os
import json
from pymongo import MongoClient

# Use the staging URI
uri = "mongodb+srv://onlearn-test:22091978@cluster0.vbs1sy5.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

client = MongoClient(uri)

def analyze_db(db_name):
    print(f"\n{'='*50}")
    print(f"Database: {db_name}")
    print(f"{'='*50}")
    db = client[db_name]
    collections = db.list_collection_names()
    
    for coll_name in collections:
        coll = db[coll_name]
        count = coll.count_documents({})
        if count == 0:
            continue
            
        print(f"\nCollection: {coll_name} (Count: {count})")
        print("-" * 30)
        
        # Get one sample
        sample = coll.find_one()
        if sample:
            # Convert ObjectId and datetime for json dump
            def default_serializer(obj):
                return str(obj)
            
            print(json.dumps(sample, default=default_serializer, indent=2)[:1000]) # Print up to 1000 chars of sample
            if len(json.dumps(sample, default=default_serializer)) > 1000:
                print("... [truncated]")

print("Analyzing interesting databases...")
analyze_db("onlearn")
analyze_db("test")

client.close()

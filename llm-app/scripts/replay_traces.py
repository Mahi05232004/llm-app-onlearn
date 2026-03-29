import asyncio
import os
import time
import json
from pymongo import MongoClient

# Add the project root to the Python path
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

async def replay_trace(trace, model):
    start_time = time.time()
    trace_id = str(trace.get("_id"))
    
    try:
        # Reconstruct message history into Langchain message objects
        # Note: The trace often contains 'message_history' inside 'input'
        input_data = trace.get("input", {})
        msg_history = input_data.get("message_history", [])
        
        langchain_messages = []
        for msg in msg_history:
            role = msg.get("role")
            content = msg.get("content", "")
            
            # Simple conversion, ignoring complex tool calls for pure latency testing
            if isinstance(content, list):
                # Sometimes content is a list of complex parts (e.g., text and tool use)
                text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
                content = "\n".join(text_parts) if text_parts else str(content)
                
            if role == "user":
                langchain_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                langchain_messages.append(AIMessage(content=content))
            elif role == "system" or role == "tool":
                langchain_messages.append(SystemMessage(content=content)) # approximate tools as system context to see raw context load
        
        # If no history, just use the current message
        if not langchain_messages:
            current_msg = input_data.get("message", "Hello")
            langchain_messages.append(HumanMessage(content=current_msg))
            
        # Estimate context size roughly
        total_chars = sum(len(str(m.content)) for m in langchain_messages)
        
        print(f"Replaying trace {trace_id}... (Context Size: ~{total_chars:,} chars)")
        
        # Execute model asynchronously
        response = await model.ainvoke(langchain_messages)
        elapsed = time.time() - start_time
        
        return {
            "trace_id": trace_id,
            "success": True,
            "elapsed": elapsed,
            "context_size": total_chars,
            "response_preview": response.content[:100].replace('\n', ' ')
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "trace_id": trace_id,
            "success": False,
            "elapsed": elapsed,
            "error": str(e)
        }

async def main():
    # Attempt to load staging ENV for MongoDB
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.staging")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ[k] = v.strip("'").strip('"')
    
    # Needs to be called after setting env vars so GeminiClient picks them up
    from app.clients.llm_client import GeminiClient
    try:
        client = GeminiClient()
        model = client.get_model()
    except Exception as e:
        print(f"Failed to initialize GeminiClient: {e}")
        return

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    print(f"Connecting to MongoDB...")
    
    try:
        db_client = MongoClient(mongo_uri)
        db = db_client["onlearn"]
        traces_coll = db["traces"]
        
        # Fetch 5 sample real traces with large histories to replay
        traces = list(traces_coll.find({}).sort("_id", -1).limit(5))
        db_client.close()
    except Exception as e:
        print(f"Database error: {e}")
        return

    print(f"Loaded {len(traces)} traces to replay.")
    print("Starting concurrent replay test...\n")
    
    # Run them all concurrently
    tasks = [replay_trace(trace, model) for trace in traces]
    results = await asyncio.gather(*tasks)
    
    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]
    
    print("\n--- Replay Test Results ---")
    for r in successes:
        print(f"[SUCCESS] Trace {r['trace_id']} - Time: {r['elapsed']:.2f}s | Context: {r['context_size']:,} chars")
    
    for r in failures:
        print(f"[FAILED]  Trace {r['trace_id']} - Time: {r['elapsed']:.2f}s | Error: {r['error']}")
        
    if successes:
        avg = sum(r["elapsed"] for r in successes) / len(successes)
        print(f"\nAverage Latency on real payloads: {avg:.2f} seconds")

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import json
import time
import uuid
import httpx
import os
from statistics import mean, median

# Target FastAPI endpoint
API_URL = "http://localhost:8000"

async def simulate_user_session(session_index: int, total_requests: int = 5):
    """Hits the chat orchestrator simulating a user navigating learn and code modes."""
    
    # Generate unique IDs for the test
    user_id = f"test_user_bench_{session_index}_{uuid.uuid4().hex[:6]}"
    session_id = f"sess_{uuid.uuid4().hex[:8]}"
    
    results = []
    
    # Test messages: mixture of initial context loading and short followups
    messages = [
        {"msg": "Student just opened session. I'm ready to learn about Arrays.", "mode": "learn"},
        {"msg": "What's the time complexity of lookup in an array?", "mode": "learn"},
        {"msg": "Can you give me an example of an array in Python?", "mode": "learn"},
        {"msg": "I am opening the code editor now to try it out.", "mode": "code"},
        {"msg": "How do I append to a list here? My code is failing.", "mode": "code"}
    ]
    
    # Simple mocked session context (normally populated by DB)
    student_profile = {"skill_level": "intermediate", "learning_goal": "interviews"}
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        for idx, turn in enumerate(messages[:total_requests]):
            payload = {
                "message": turn["msg"],
                "sessionId": session_id,
                "user_id": user_id,
                "mode": turn["mode"],
                "module": "dsa",
                "files": {
                    "/student_profile.json": {
                        "content": json.dumps(student_profile),
                        "metadata": {"type": "json"}
                    },
                    "/topic.json": {
                        "content": json.dumps({"topic_id": "test_arrays_01"}),
                        "metadata": {"type": "json"}
                    }
                }
            }
            
            print(f"[{session_index}-{idx}] Sending request: {turn['msg'][:30]}... (Mode: {turn['mode']})")
            
            start_time = time.time()
            ttft = None
            response_chunks = []
            
            try:
                # Use the streaming endpoint to measure Time-To-First-Token
                async with client.stream("POST", f"{API_URL}/chat/stream", json=payload) as response:
                    async for line in response.aiter_lines():
                        if not line: continue
                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])
                                if data.get("type") in ["token", "thinking"] and ttft is None:
                                    ttft = time.time() - start_time
                                if data.get("type") == "token":
                                    response_chunks.append(data.get("content", ""))
                            except json.JSONDecodeError:
                                pass
                                
                end_time = time.time()
                total_time = end_time - start_time
                full_response = "".join(response_chunks)
                
                results.append({
                    "session": session_index,
                    "turn": idx,
                    "mode": turn["mode"],
                    "latency_total": total_time,
                    "ttft": ttft or total_time,
                    "response_length": len(full_response),
                    "success": True,
                })
                print(f"  -> TTFT: {ttft:.2f}s | Total: {total_time:.2f}s | Chars: {len(full_response)}")
                
            except Exception as e:
                print(f"  -> ERROR: {e}")
                results.append({
                    "session": session_index,
                    "turn": idx,
                    "success": False,
                    "error": str(e)
                })
                
    return results

async def main():
    print("Starting Live Trace Benchmarking against local FastAPI...")
    # We will simulate 6 concurrent "users", each doing 5 requests = 30 live tests total
    concurrent_users = 6
    tasks = [simulate_user_session(i) for i in range(concurrent_users)]
    
    all_results_nested = await asyncio.gather(*tasks)
    
    # Flatten results
    all_results = [res for session_res in all_results_nested for res in session_res]
    
    # Save raw data
    with open("live_traces.json", "w") as f:
        json.dump(all_results, f, indent=2)
        
    print(f"\nSaved {len(all_results)} trace results to live_traces.json")
    
    # Analyze
    successes = [r for r in all_results if r["success"]]
    failures = [r for r in all_results if not r["success"]]
    
    if successes:
        ttfts = [r["ttft"] for r in successes]
        totals = [r["latency_total"] for r in successes]
        
        print("\n=== LATENCY ANALYSIS ===")
        print(f"Total Requests: {len(all_results)} ({len(successes)} successful, {len(failures)} failed)")
        print(f"Avg Time-To-First-Token (TTFT): {mean(ttfts):.2f}s (Median: {median(ttfts):.2f}s)")
        print(f"Avg Total Latency: {mean(totals):.2f}s (Median: {median(totals):.2f}s)")

if __name__ == "__main__":
    asyncio.run(main())

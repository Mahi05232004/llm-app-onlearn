import asyncio
import os
import sys
import time

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.clients.llm_client import GeminiClient

async def make_request(model, idx):
    start_time = time.time()
    try:
        response = await model.ainvoke(f"Repeat after me: This is test message {idx} and I am functioning well.")
        elapsed = time.time() - start_time
        return {"id": idx, "success": True, "elapsed": elapsed, "content": response.content}
    except Exception as e:
        elapsed = time.time() - start_time
        return {"id": idx, "success": False, "elapsed": elapsed, "error": str(e)}

async def main():
    try:
        client = GeminiClient()
        model = client.get_model()
    except Exception as e:
        print(f"Failed to initialize GeminiClient: {e}")
        return

    num_requests = int(os.environ.get("STRESS_TEST_CALLS", 10))
    print(f"Starting stress test with {num_requests} concurrent requests...")
    
    start_total = time.time()
    
    tasks = [make_request(model, i) for i in range(num_requests)]
    results = await asyncio.gather(*tasks)
    
    total_elapsed = time.time() - start_total
    
    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]
    
    print("\n--- Stress Test Results ---")
    print(f"Total Requests: {num_requests}")
    print(f"Total Time: {total_elapsed:.2f} seconds")
    print(f"Successful: {len(successes)}")
    print(f"Failed: {len(failures)}")
    
    if successes:
        avg_time = sum(r["elapsed"] for r in successes) / len(successes)
        print(f"Average time per successful request: {avg_time:.2f} seconds")
        
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  Request {f['id']} failed in {f['elapsed']:.2f} seconds: {f['error']}")

if __name__ == "__main__":
    asyncio.run(main())

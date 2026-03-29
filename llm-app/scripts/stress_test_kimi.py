import asyncio
import time
import argparse
from app.clients.llm_client import AzureLLMClient

async def make_request(client, prompt: str, req_id: int):
    print(f"[{req_id}] Starting request...")
    start_time = time.time()
    try:
        model = client.get_model()
        # We use invoke instead of stream for a simpler load test,
        # or we can just stream and consume it
        response = await model.ainvoke(prompt)
        duration = time.time() - start_time
        print(f"[{req_id}] Finished in {duration:.2f}s. Response length: {len(response.content)}")
        return {"id": req_id, "duration": duration, "success": True, "error": None}
    except Exception as e:
        duration = time.time() - start_time
        print(f"[{req_id}] Failed in {duration:.2f}s. Error: {e}")
        return {"id": req_id, "duration": duration, "success": False, "error": str(e)}

async def main():
    parser = argparse.ArgumentParser(description="Stress test Kimi k2.5")
    parser.add_argument("--concurrency", type=int, default=10, help="Number of concurrent requests")
    parser.add_argument("--total", type=int, default=20, help="Total number of requests to send")
    args = parser.parse_args()
    
    print(f"Initializing AzureLLMClient...")
    client = AzureLLMClient()
    
    print(f"Starting stress test: {args.total} total requests, {args.concurrency} concurrent.")
    
    prompt = "Write a short poem about the ocean and the stars. Be creative and return exactly 4 lines."
    
    semaphore = asyncio.Semaphore(args.concurrency)
    
    async def bounded_request(req_id):
        async with semaphore:
            return await make_request(client, prompt, req_id)
            
    start_time = time.time()
    tasks = [bounded_request(i) for i in range(args.total)]
    results = await asyncio.gather(*tasks)
    total_duration = time.time() - start_time
    
    success_count = sum(1 for r in results if r["success"])
    error_count = sum(1 for r in results if not r["success"])
    
    print("\n--- Stress Test Results ---")
    print(f"Total Time: {total_duration:.2f}s")
    print(f"Successful Requests: {success_count}/{args.total}")
    print(f"Failed Requests: {error_count}/{args.total}")
    
    if success_count > 0:
        avg_time = sum(r["duration"] for r in results if r["success"]) / success_count
        print(f"Average Request Duration (Success): {avg_time:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import os
import time
import json
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load staging ENV
env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.staging")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k] = v.strip("'").strip('"')

from app.clients.llm_client import GeminiClient
from langchain_core.messages import HumanMessage, SystemMessage


async def replay_trace(trace, model, index):
    """Replay a single trace against Gemini using the exact input from production."""
    trace_id = trace.get("_id", "unknown")
    inp = trace.get("input", {})
    original_duration = trace.get("duration_ms")

    # 1. Build context from files (system message)
    files = inp.get("files", {})
    file_context_parts = []
    file_sizes = {}
    for fname, fdata in files.items():
        content = fdata.get("content", "")
        if isinstance(content, list):
            content = "\n".join(content)
        file_sizes[fname] = len(content)
        file_context_parts.append(f"--- {fname} ---\n{content}")

    files_context = "\n\n".join(file_context_parts)

    # 2. Build the user message (the actual user input)
    user_msg = inp.get("message", "")
    mode = inp.get("mode", "learn")

    messages = []
    if files_context:
        messages.append(SystemMessage(content=files_context))
    messages.append(HumanMessage(content=f"[{mode.upper()}] {user_msg}"))

    total_chars = sum(len(m.content) for m in messages)
    print(f"[{index:2d}] trace={trace_id[:12]}  mode={mode:<5}  context={total_chars:>7,} chars  files={list(file_sizes.keys())}")

    # 3. Stream the response to capture TTFT
    start = time.time()
    ttft = None
    full_response = ""

    try:
        async for chunk in model.astream(messages):
            if ttft is None:
                ttft = time.time() - start
            if chunk.content:
                if isinstance(chunk.content, str):
                    full_response += chunk.content
                elif isinstance(chunk.content, list):
                    for p in chunk.content:
                        if isinstance(p, dict) and "text" in p:
                            full_response += p["text"]

        total = time.time() - start
        print(f"     -> TTFT: {ttft:.2f}s  Total: {total:.2f}s  Response: {len(full_response):,} chars"
              f"  (original: {original_duration}ms)")

        return {
            "trace_id": trace_id,
            "success": True,
            "mode": mode,
            "user_message": user_msg[:100],
            "ttft": round(ttft, 3),
            "total_time": round(total, 3),
            "context_chars": total_chars,
            "response_chars": len(full_response),
            "response_preview": full_response[:200],
            "original_duration_ms": original_duration,
            "file_sizes": file_sizes,
        }

    except Exception as e:
        elapsed = time.time() - start
        print(f"     -> ERROR after {elapsed:.2f}s: {e}")
        return {
            "trace_id": trace_id,
            "success": False,
            "error": str(e),
            "total_time": round(elapsed, 3),
            "mode": mode,
            "context_chars": total_chars,
        }


async def main():
    # Load the raw traces dumped by mongosh
    traces_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "raw_mongo_traces.json")
    if not os.path.exists(traces_file):
        print(f"❌ File not found: {traces_file}")
        return

    with open(traces_file) as f:
        traces = json.load(f)

    print(f"Loaded {len(traces)} traces from {traces_file}\n")

    # Init Gemini
    print("Initializing Gemini (with fallback)...")
    client = GeminiClient()
    model = client.get_model_with_fallback()
    print(f"Model ready.\n")

    results = []

    for idx, trace in enumerate(traces):
        res = await replay_trace(trace, model, idx + 1)
        results.append(res)

        # Save incrementally
        out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "replay_results_fast_fallback.json")
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)

        # Delay to avoid rate limits
        await asyncio.sleep(2)

    # ── Summary ──
    print("\n" + "=" * 60)
    print("REPLAY COMPLETE")
    print("=" * 60)

    ok = [r for r in results if r["success"]]
    fail = [r for r in results if not r["success"]]

    print(f"Total: {len(results)}  |  Success: {len(ok)}  |  Failed: {len(fail)}")

    if ok:
        ttfts = [r["ttft"] for r in ok]
        totals = [r["total_time"] for r in ok]
        contexts = [r["context_chars"] for r in ok]

        print(f"\nTTFT     — Avg: {sum(ttfts)/len(ttfts):.2f}s  Min: {min(ttfts):.2f}s  Max: {max(ttfts):.2f}s")
        print(f"Total    — Avg: {sum(totals)/len(totals):.2f}s  Min: {min(totals):.2f}s  Max: {max(totals):.2f}s")
        print(f"Context  — Avg: {sum(contexts)//len(contexts):,} chars  Min: {min(contexts):,}  Max: {max(contexts):,}")

    if fail:
        print(f"\nFailed traces:")
        for r in fail:
            print(f"  {r['trace_id']}: {r['error']}")

    print(f"\nFull results saved to replay_results.json")


if __name__ == "__main__":
    asyncio.run(main())

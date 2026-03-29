import asyncio
import os
import sys
import time

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.clients.llm_client import GeminiClient
from langchain_core.messages import HumanMessage

async def main():
    try:
        client = GeminiClient()
        model = client.get_model()
    except Exception as e:
        print(f"Failed to initialize GeminiClient: {e}")
        return

    # Create a large block of text
    # 1 repetition: ~235 characters, ~50 words.
    base_text = "The quick brown fox jumps over the lazy dog. Here is some more filler text to increase the context size without adding too much complexity to the actual generation task. We just want to measure the input processing time of the model. "
    repetitions = 1000  # ~235,000 characters, ~50,000+ tokens
    
    large_input = base_text * repetitions
    prompt = f"Please read the following long text and summarize it in exactly one short sentence. Ignore the repetitive filler and just say what it talks about:\n\n{large_input}"
    
    print(f"Testing Gemini latency with large input...")
    print(f"Input size: {len(prompt):,} characters (approx. {len(prompt) // 4:,} tokens).")
    
    start_time = time.time()
    
    print("Waiting for response...")
    try:
        response = await model.ainvoke([HumanMessage(content=prompt)])
        elapsed = time.time() - start_time
        print(f"\n--- SUCCESS ---")
        print(f"Time Taken: {elapsed:.2f} seconds")
        print(f"Response Content:\n{response.content[:500]}...") # truncate if it's too long
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n--- FAILED ---")
        print(f"Time taken before failure: {elapsed:.2f} seconds")
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())

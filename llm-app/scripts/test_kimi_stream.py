import asyncio
import os
import time
import json
from dotenv import load_dotenv

# Load .env.dev
load_dotenv(".env.dev")

from app.clients.llm_client import AzureLLMClient
from app.api.helpers.sse_streaming import stream_agent_events

class MockAgent:
    def __init__(self, model):
        self.model = model
    
    async def astream_events(self, inputs, config, version="v2"):
        # Simulate LangGraph astream_events for the model
        messages = inputs.get("messages", [])
        async for chunk in self.model.astream(messages):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": chunk},
                "tags": []
            }

async def test_direct_stream(model_type: str = "default"):
    print(f"\n=== Testing Direct Model Stream ({model_type}) ===")
    client = AzureLLMClient()
    model = client.get_model(model_type=model_type)
    
    print(f"Model: {getattr(model, 'model_name', 'unknown')}")
    print("Sending prompt...")
    
    start_time = time.time()
    first_token_time = None
    
    async for chunk in model.astream("Which is larger: 9.9 or 9.11? Think step by step and output your reasoning before the final answer."):
        current_time = time.time()
        elapsed = current_time - start_time
        
        if first_token_time is None:
            first_token_time = elapsed
            print(f"\n[First Token] Time to first token: {first_token_time:.2f}s")
            
        reasoning = chunk.additional_kwargs.get("reasoning_content", "")
        content = chunk.content
        
        if reasoning:
            print(f"[REASONING] ({elapsed:.2f}s): {repr(reasoning)}")
        if content:
            print(f"[CONTENT] ({elapsed:.2f}s): {repr(content)}")

async def test_helper_stream():
    print("\n=== Testing stream_agent_events Helper ===")
    client = AzureLLMClient()
    model = client.get_model()
    
    agent = MockAgent(model)
    inputs = {"messages": [("user", "Explain quantum computing roughly to a 5 year old.")]}
    config = {"configurable": {"thread_id": "test"}}
    
    print("Streaming through helper...")
    start_time = time.time()
    
    async for event in stream_agent_events(agent, inputs, config):
        elapsed = time.time() - start_time
        print(f"[EVENT] ({elapsed:.2f}s): {repr(event)}")

async def main():
    # Test Kimi (default)
    print("\n--- Testing Kimi K2.5 ---")
    await test_direct_stream(model_type="default")
    
    # Test Grok (fallback)
    print("\n--- Testing Grok 4 Reasoning ---")
    await test_direct_stream(model_type="grok-4-fast-reasoning")

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import time
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from app.clients.llm_client import AzureLLMClient

@tool
def get_weather(location: str):
    """Get the weather for a location."""
    return f"Weather in {location} is sunny."

async def test_tool_stream():
    client = AzureLLMClient()
    model = client.get_model()
    # Bind the tool
    model_with_tools = model.bind_tools([get_weather])
    
    print("\n=== Testing Tool Call Stream ===")
    prompt = "What's the weather like in Paris?"
    
    # We use astream_events to inspect chunks
    # Actually direct .astream should also yield chunk.tool_call_chunks
    async for chunk in model_with_tools.astream(prompt):
        if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
            print(f"\n[TOOL CHUNK]: type={type(chunk.tool_call_chunks[0])}")
            for tc in chunk.tool_call_chunks:
                print(f"  Name: {tc.get('name')}")
                print(f"  Args: {tc.get('args')}")
                print(f"  ID:   {tc.get('id')}")
        elif chunk.content:
            print(f"Content: {repr(chunk.content)}")

if __name__ == "__main__":
    import sys
    sys.path.append('.')
    asyncio.run(test_tool_stream())

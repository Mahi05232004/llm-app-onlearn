import asyncio
import os
import sys

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.clients.llm_client import GeminiClient

async def main():
    print("Checking LLM API connectivity...")
    try:
        client = GeminiClient()
        model = client.get_model()
        
        response = await model.ainvoke("Hello! Are you working?")
        print("\nSuccess! LLM API is working.")
        print("Response:", response.content)
        
    except Exception as e:
        print("\nError: Failed to connect or get response from LLM API.")
        print(f"Exception: {e}")

if __name__ == "__main__":
    asyncio.run(main())

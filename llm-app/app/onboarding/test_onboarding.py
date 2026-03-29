import asyncio
import uuid
from app.onboarding.agent import get_onboarding_agent

async def main():
    print("🧪 Starting Onboarding Agent Test")
    
    # generate valid ObjectId for session/user
    from bson import ObjectId
    user_id = str(ObjectId())
    print(f"👤 User ID (Session ID): {user_id}")
    
    print("🤖 Loading Agent...")
    try:
        agent = get_onboarding_agent()
    except Exception as e:
        print(f"❌ Failed to load agent: {e}")
        return

    print("\n✅ Agent Loaded. Starting Chat.")
    
    # 1. Start Onboarding
    print("\n[User]: [START_ONBOARDING]")
    thread_id = f"onboarding_{user_id}"
    config = {"configurable": {"thread_id": thread_id, "assistant_id": user_id}}
    
    inputs = {
        "messages": [("user", "Hi, I'm new here and want to start learning!")],
        "user_id": user_id,
    }
    
    try:
        async for event in agent.astream_events(inputs, config=config, version="v2"):
            kind = event.get("event")
            
            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    print(content, end="", flush=True)
            
            elif kind == "on_tool_start":
                print(f"\n[Tool Call]: {event['name']}")
                
    except Exception as e:
        print(f"\n❌ Error during stream: {str(e)}")

    print("\n\nTest Complete.")

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import uuid
import os
import sys

# Ensure the app module is in the python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from app.tutor import get_tutor_agent
from app.tutor.core.workspace import initialize_tutor_workspace
from app.tutor.core.store import get_tutor_store

async def main():
    # 1. Setup - Create a random test user
    user_id = f"cli_test_user_{uuid.uuid4().hex[:8]}"
    print(f"🧪 Starting CLI Test for User ID: {user_id}")
    
    # Use the existing store connection logic
    store = get_tutor_store()
    
    # 2. Initialize Workspace (Seeds AGENTS.md, etc.)
    print("📂 Initializing workspace...")
    await initialize_tutor_workspace(store, user_id)
    
    # 3. Get the Agent Graph
    print("🤖 Loading Tutor Agent...")
    agent = get_tutor_agent(module="dsa")
    
    # 4. Interactive Chat Loop
    thread_id = f"tutor_{user_id}"
    config = {"configurable": {"thread_id": thread_id}}
    
    print("\n✅ Verification Complete. Starting Chat Session.")
    print("Type 'exit' to quit.\n")
    
    while True:
        try:
            user_input = input("You: ")
            if user_input.lower() in ("exit", "quit"):
                break
            
            inputs = {
                "messages": [{"role": "user", "content": user_input}]
            }
            
            print("Tutor: ", end="", flush=True)
            async for event in agent.astream(inputs, config=config):
                if "messages" in event:
                    # Depending on checkpointer/graph, 'messages' might be returned directly
                    pass
                
                # Check for agent output in the stream
                for node_name, node_output in event.items():
                    if isinstance(node_output, dict) and "messages" in node_output:
                        msgs = node_output["messages"]
                        if isinstance(msgs, list) and len(msgs) > 0:
                            last_msg = msgs[-1]
                            if hasattr(last_msg, 'content'):
                                print(last_msg.content)
                        else:
                            # Debug: messages is not a list
                            # print(f"Node {node_name} 'messages' type: {type(msgs)}")
                            pass
                    else:
                        pass

                        
        except KeyboardInterrupt:
            break
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"\n❌ Error: {e}")
            break

if __name__ == "__main__":
    asyncio.run(main())

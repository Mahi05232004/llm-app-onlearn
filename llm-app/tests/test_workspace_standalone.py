import asyncio
import sys
from langgraph.store.memory import InMemoryStore
from app.tutor.core.workspace import initialize_tutor_workspace

async def main():
    print("Initializing store...")
    store = InMemoryStore()
    user_id = "test_standalone_user"
    
    print(f"Calling initialize_tutor_workspace for {user_id}...")
    await initialize_tutor_workspace(store, user_id)
    print("Done initializing.")
    
    print("Checking /AGENTS.md...")
    agents = await store.aget((user_id,), "/AGENTS.md")
    print(f"/AGENTS.md: {agents is not None}")
    
    print("Checking /todos.md...")
    todos = await store.aget((user_id,), "/todos.md")
    print(f"/todos.md: {todos is not None}")

if __name__ == "__main__":
    asyncio.run(main())

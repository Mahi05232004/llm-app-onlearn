import asyncio
from app.modules.__init__ import get_module
from app.api.endpoints.orchestrator import _build_onboarding_graph
from langgraph.graph import StateGraph
from app.onboarding.agent import _build_onboarding_graph as build_graph_real

async def main():
    dsa_config = get_module("dsa")
    
    # We load the real graph logic
    graph = build_graph_real(dsa_config.onboarding_prompt)
    compiled = graph.compile()
    
    inputs = {
        "messages": [("user", "Hi, I'm new here and want to start learning!")],
    }
    
    config = {
        "configurable": {"thread_id": "test_dsa"},
    }
    
    result = await compiled.ainvoke(inputs, config=config)
    print("Agent Response:")
    print(result["messages"][-1].content)

if __name__ == "__main__":
    asyncio.run(main())

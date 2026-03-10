# llm-app-onlearn

This repository contains the LLM (Large Language Model) component of the complete **OnLearn** project.

## Overview
This codebase specifically showcases the **deep-agents integration** and **multi-agent orchestration** elements of the larger OnLearn platform. It has been separated from the main repository to highlight the AI architecture while keeping sensitive configuration out of the public domain.

> **Note:** The complete OnLearn codebase is held in a private repository due to the complexity of the full application and the inherent security risks associated with exposing necessary environment variables and sensitive configurations.

## Architecture Deep Dive

The `llm-app` functions as a specialized microservice within the OnLearn ecosystem. It is built to handle complex, stateful interactions with users through a sophisticated multi-agent AI system.

### Core Technologies
- **FastAPI**: Provides a high-performance, asynchronous REST API layer for seamless communication with the main OnLearn backend and frontend.
- **LangChain & LangGraph**: Serves as the backbone for the agentic workflows, enabling stateful, cycled execution of LLM prompts and tool-calling graphs.
- **MongoDB**: Used for persistent state management, logging conversational histories, and storing agent checkpoints.

### Multi-Agent Orchestration
The heart of the application (`app/supervisor/`) is an orchestrated graph that routes dynamic learning interactions through specialized AI agents:

1. **Master Agent**: The primary coordinator. It interprets the student's intent, tracks their overall progress across the course, and delegates tasks to the specialized sub-agents.
2. **Planner Agent**: Responsible for generating, personalizing, and dynamically adjusting the student's learning pathway based on their pace and preferences. 
3. **Concept Tutor (Learn Mode)**: Focuses on delivering theoretical knowledge, explaining complex topics, and answering conceptual questions without giving away immediate answers.
4. **Lab Mentor (Code Mode)**: A specialized pedagogical agent that assists students when they are actively coding. It helps debug, provides hints, and guides the student towards the correct implementation.
5. **Guide Agent**: Handles general inquiries and navigational assistance across the platform.

### Workflow Execution
- **State Management**: Each learning session maintains a persistent state (via LangGraph Checkpointers and MongoDB) to remember the current topic, previous user mistakes, and overall context.
- **Code Execution Pipeline**: Integrates with secure, sandboxed execution environments (`api/execution.py` and `api/validation.py`) to evaluate user code submissions against test cases and pass the results back to the `Lab Mentor` for targeted feedback.
- **Adaptive Planning**: Uses dedicated planning graphs (`app/planning/`) to adapt the curriculum on-the-fly depending on user performance.
# OnLearn AI Engine: Multi-Agent Pedagogical Orchestration

Welcome to the **OnLearn AI Engine**! This repository houses the sophisticated "AI Brain" of the OnLearn platform. It is a state-of-the-art, multi-agent pedagogical system built on **LangGraph** and **DeepAgents**, specifically engineered to provide an adaptive, 1-on-1 tutoring experience for Data Structures and Algorithms (DSA) and Data Science (DS).

> [!NOTE]  
> **Repository Scope**: This codebase specifically contains the AI logic, agent orchestration, and pedagogical backend. The complete OnLearn platform (including the UI/Frontend and auxiliary non-AI microservices) is managed in a separate repository to ensure modularity and security.

---

## Architectural Vision: The Multi-Agent Faculty

OnLearn isn't just a chatbot; it's a **distributed intelligence hardware**. We solve the "context bloat" common in monolithic LLM agents by splitting pedagogical responsibilities across a team of specialized **Multi-Agent Skills**. 

Following the **Multi-Agent Architecture**, every student interaction flows through a structured hierarchy:

### 1. The Multi-Agent Hierarchy
*   **Planner Agent** (`app/planning/`): The curriculum architect. When a user enters the platform, the Planner asks the right questions and creates a **Global Plan** (12-week curriculum) tailored to their level.
*   **Master Agent** (`app/tutor/dsa/agent.py`): The core orchestrator. It maintains the "Learning Journey" state, manages memory, and delegates work to specialized skills.
*   **Session Planner skill** (`concept-tutor` / `lab-mentor` / `session-planner`): Generates the **Session To-Do List**, scoping specific tasks for the specialized tutors.
*   **Concept Tutor Agent** (`app/tutor/core/skills/concept-tutor`): The theory professor. It uses analogies and Socratic questioning to **Teach & Guide Concepts**.
*   **Lab Mentor Agent** (`app/tutor/core/skills/lab-mentor`): The coding coach. It has tools to **Evaluate & Debug Code** in real-time.
*   **Progress Reporter**: Updates the student's **Progress & Results** in MongoDB, looping back to the Master Agent for the next turn.

### Key Technical Pillars
*   **Multi-Agent Orchestration**: Powered by `LangGraph` for complex, cyclical state management.
*   **DeepAgent Framework**: A modular architecture that separates "Core Logic" (Master Agent) from "Pedagogical Skills" (Specialist Agents), allowing for rapid skill deployment.
*   **Azure AI Inference + Kimi-k2.5**: Leveraging reasoning-focused models via Azure's enterprise-grade infrastructure.
*   **Semantic RAG Middleware**: Automatic summarization and vector-offloading of conversation history.
*   **Dual-Layer Memory**: 
    *   **Short-term**: `short_term_plan.md` for session-specific tasks.
    *   **Long-term**: `AGENTS.md` (Student Profile) and `global_plan.md` persisted via MongoDB.

---

## Key Highlights & Features

The OnLearn AI Engine is packed with features designed for high-agency pedagogical interaction:

*   **Voice-First Interaction**: Integrated with **Azure AI Speech** for real-time TTS/STT, allowing students to learn via natural conversation.
*   **Dynamic Week-wise Planning**: A dedicated **Planner Agent** generates a fully personalized curriculum based on technical level and time commitments.
*   **AI-Generated Daily Reports**: Automatically sends progress summaries and "streak reminders" via **Resend** to boost student retention.
*   **Socratic Debugging**: Specialized **Lab Mentor** logic that identifies code errors but guides the student to the fix through hints rather than raw solutions.
*   **Context-Aware Suggestions**: After every turn, the engine generates "Next Action" buttons (e.g., *"Try a similar problem"*, *"Explain this concept further"*) to keep the learning momentum.
*   **High-Fidelity Reasoning**: Optimized for **Kimi-k2.5** with custom handling for `reasoning_content` to surface the AI's internal chain-of-thought tokens.
*   **Secure Workspace**: A virtualized Python execution environment for running and testing student code against hidden test cases.

---

## 📂 Repository Deep Dive

### 1. `app/` — The Intelligence Layer
The core of the system resides here:

*   **`app/tutor/`**: The primary interaction engine containing the Master Agent logic.
    *   **`core/skills/`**: The implementation of the **Multi-Agent specialist roles** (Concept Tutor, Lab Mentor, Session Planner).
    *   **`core/tools/`**: Domain-specific tools (e.g., `execute_code.py` sandbox, `learning_plan.py` CRUD).
    *   **`core/middleware/`**: Intercepts messages to inject context, tag modes, or prune history.
*   **`app/planning/`**: The **Planner Agent** logic for generating personalized 12-week paths.
*   **`app/onboarding/`**: The interviewer agent that builds the initial student profile.

### 2. `api/` — The Communication Layer
Exposes the AI Engine to the frontend via FastAPI.
*   **`orchestrator.py`**: The main SSE streaming endpoint handling the Master Agent's turn sequence.
*   **`execution.py`**: Secure bridge for the Lab Mentor to run Python code.

### 3. `core/` & `models/` — The Foundation
*   **`core/mongo_db.py`**: Driver for student state, curriculum, and long-term memory.
*   **`core/checkpointer.py`**: Persists agent history across turns.
*   **`models/`**: Pydantic schemas for Course Concepts, Plans, and Tasks.

---

## 🛠 Tech Stack

| Component | Technology |
| :--- | :--- |
| **Model Hosting** | Azure AI Inference |
| **LLMs** | Kimi-k2.5 (Moonshot), text-embedding-3-small |
| **Framework** | LangGraph, LangChain, DeepAgents |
| **Backend** | FastAPI, Python 3.13+ |
| **Database** | MongoDB (State, Store, Vectors) |
| **Package Management** | `uv` |

---

## ⚙️ Setup & Configuration

### Environment Variables
Create a `.env` file based on `.env.template`:
```env
# Azure Credentials
AZURE_OPENAI_API_KEY="..."
AZURE_OPENAI_ENDPOINT="..."
AZURE_OPENAI_API_VERSION="..."

# Database
MONGO_URI="mongodb://..."
```

### Quick Start
```bash
uv sync
uv run python -m api.main
```

---

## 🛡 License & Disclaimer
This repository is the AI Logic core of **OnLearn**. For platform access, please contact the maintainers. This is specifically the pedagogical engine and requires the OnLearn Frontend to function as intended.
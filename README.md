# llm-app-onlearn: Multi-Agent LLM Backend

Welcome to the **llm-app-onlearn** repository! 

This codebase contains the AI brain of the larger **OnLearn** platform. It has been separated from the main repository to highlight how we use **Large Language Models (LLMs)** and **Multi-Agent Orchestration** to create a highly personalized, interactive learning experience.

> **Note:** The complete OnLearn codebase (including the frontend and non-AI backend services) is held in a private repository due to the complexity of the full application and the need to secure sensitive database and cloud credentials.

---

## What is this Project?

Imagine a teaching platform where the AI doesn't just answer questions, but actively functions as a personalized teacher. It remembers what you struggle with, adjusts the lesson plan, teaches you concepts, and helps you debug code without giving away the answers. 

To achieve this, a single AI prompt is not enough. Instead, this project uses a **Multi-Agent System**—a team of specialized AI bots that talk to each other to guide a student through a course.

### Core Technologies Used
- **FastAPI**: The high-speed Python web framework that serves as the communication bridge between this AI engine and the frontend.
- **LangChain & LangGraph**: The libraries that power our AI. Instead of a simple chat loop, LangGraph allows us to build complex, cyclical "graphs" where agents can think, use tools, and pass control to one another.
- **MongoDB**: The database used to save the student's progress, store the course curriculum, and natively log the AI conversation history so the agents can "remember" past interactions.

---

## Directory Structure (A Beginner's Guide)

Here is a breakdown of what each folder in this repository does:

```text
llm-app/
├── api/             # The API Entrypoints (FastAPI)
├── app/             # The Core AI Logic & Agents (LangGraph)
├── core/            # System configurations & Database connections
├── models/          # Data Schemas (Pydantic models)
├── services/        # Helper functions (e.g., generating embeddings)
└── tests/           # Testing the AI workflows
```

### 1. The `api/` Directory
This folder contains the FastAPI endpoints. When the frontend wants the AI to do something, it sends a request here.
- `main.py`: The entry point that starts the server and loads all the routes.
- `courses.py` / `execution.py` / `validation.py`: Endpoints for fetching course data, executing the student's code securely, and validating if their code passed the required tests.

### 2. The `core/` and `models/` Directories
- **`core/`**: Handles the foundation. `mongo_db.py` manages the database connection, and `course_data.py` loads the curriculum.
- **`models/`**: Defines the exact structure of our data using Pydantic. E.g., `concept.py` defines what a "Course Concept" looks like so the AI knows exactly what fields to expect.

### 3. The `app/supervisor/` Directory (The Heart of the AI)
This is where the magic happens. We use **LangGraph** to build a `supervisor` system that acts like a school faculty.

Inside `app/supervisor/`:
- **`orchestrator.py`**: The principal. It compiles the entire AI graph, setting up the rules for how agents talk to each other.
- **`state/state.py`**: The memory. It defines what information is passed between agents (e.g., the current topic, the chat history, the student's code).

#### The Agents (`app/supervisor/agents/`):
Because a single LLM gets easily confused if it tries to do too many things, we split the responsibilities:

1. **Master Agent**: The receptionist/manager. When a user sends a message, it always goes here first. The Master Agent decides what the user wants and forwards the message to the correct specialist.
2. **Planner Agent**: The curriculum designer. It looks at the user's progress and updates their personalized learning plan dynamically.
3. **Concept Tutor**: The theory professor. It uses a specific prompt to teach theoretical topics. It is instructed to guide the user to the answer, *never* just spoon-feeding it.
4. **Lab Mentor**: The coding assistant. When the user is stuck on a coding problem, the Lab Mentor steps in. It has access to **Tools** (`app/supervisor/tools/`) like `execute.py` which allows the AI to actually run the student's code, see the error, and provide a helpful hint.

---

## How a Conversation Flows (The Architecture)

When a student sends a message saying *"My code isn't working"*:
1. **API receives request**: The `api/` folder catches the HTTP request.
2. **Master Agent decides**: The request is pushed into the `orchestrator.py` graph. The Master Agent reads it and thinks: *"This is a coding issue. I need to route this to the Lab Mentor."*
3. **Lab Mentor takes over**: The Lab Mentor agent receives the state. It uses the `execute` tool to run the student's code in a secure environment.
4. **Tool returns result**: The execution tool tells the Lab Mentor: *"The code failed with a SyntaxError on line 4."*
5. **Lab Mentor responds**: The Lab Mentor generates a friendly response: *"It looks like you missed a colon at the end of your if-statement on line 4. Try fixing that!"*
6. **State saved**: The conversation and progress are saved securely to MongoDB via `core/checkpointer.py`.
7. **Response sent back**: FastAPI sends the Lab Mentor's response back to the user's screen.

> By breaking the system down into specific agents and giving them targeted tools (like code execution), the AI becomes incredibly accurate and helpful, simulating a real 1-on-1 tutoring experience!
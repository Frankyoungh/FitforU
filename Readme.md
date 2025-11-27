# FitForU – Intelligent Health Assistant Agent System

FitForU is an LLM-based multi-agent health assistant that turns users’ free-text health goals into **structured, executable daily routines**. It generates personalised plans, schedules them into calendar events, and guards against unsafe “doctor-like” answers through a multi-gate risk-control pipeline.

The system runs with a locally deployed LLM (via Ollama) and a lightweight Streamlit web UI.

---

## 1. Project Overview

Mainstream text-based health assistants often:

- give generic, non-personalised suggestions;
- output fragmented tips instead of full routines;
- make it hard to turn advice into concrete daily actions;
- occasionally produce unsafe, diagnosis-like answers.

FitForU addresses these issues by:

1. **Planning** – converting natural-language health goals into structured multi-day plans.  
2. **Scheduling** – turning plans into time-anchored events that can be imported into calendar apps.  
3. **Retrieval-augmented Q&A** – grounding answers in a local knowledge base when evidence is available.  
4. **Risk Guard + Verifier** – enforcing safety and policy constraints before any plan is exported.

---

## 2. Key Features

- 🧠 **Multi-agent pipeline**

  A unified pipeline coordinates several agents:

  - **Intent Router** – classifies incoming requests (small talk / health Q&A / planning / adjustment).  
  - **Planner** – designs high-level health plans and decomposes them into modules.  
  - **Composer / Scheduler** – converts plans into day-by-day routines under user constraints.  
  - **Risk Guard & Verifier** – checks both Q&A and plans for unsafe or over-confident content.  
  - **Act / Deliver** – exports ICS files and renders checklists; supports replay and adjustment.

- 📅 **Executable health plans**

  - Generates structured JSON plans with:
    - plan type (e.g. fat loss, rehab, beginner strength),
    - time horizon and weekly structure,
    - modules (training, diet, recovery, habits, etc.),
    - constraints (available time, taboo exercises).
  - Schedules modules into daily routines, respecting:
    - time windows,
    - maximum daily duration,
    - muscle-group recovery intervals,
    - unavailable dates.
  - Exports **RFC-5545-compliant `.ics` files** that can be imported into Google Calendar, Outlook, etc.

- 🛡 **Layered safety & compliance**

  - **Input gate (G0)** for obviously high-risk queries.  
  - **Q&A output gate** for hallucinated “diagnoses” or prescriptions.  
  - **Plan pre-check & post-check** to catch dangerous, overloaded, or inconsistent plans.  
  - High-risk content is blocked, downgraded, or rewritten with safer guidance instead of pretending to be a doctor.

- 📚 **Local knowledge base (RAG)**

  - Automatically loads documents from a local knowledge directory.  
  - Uses TF-IDF retrieval to fetch relevant snippets for planning and health Q&A.  
  - Answers can be explicitly grounded in retrieved passages.

- 👤 **Long-term user profile & plan adjustment**

  - Stores user preferences (time windows, maximum daily load, preferred styles, taboo movements).  
  - Supports “rolling rearrangement”: users can mark tasks done / cancelled and regenerate the remaining schedule.  
  - Maintains history so that future plans can adapt to adherence and feedback.

- 🌐 **Bilingual Web UI**

  - Streamlit front-end with model selector and decoding parameters.  
  - Supports both **Chinese and English** for input and output.  
  - Separate tabs / modes for:
    - general chat & health Q&A,
    - new plan generation,
    - current plan adjustment and export.

---

## 3. Core Modules & Files

> File names may differ slightly depending on the final repository layout. Adjust descriptions if needed.

| Module / File                  | Description |
|--------------------------------|-------------|
| `application/FitForU_web.py`   | Main entry point and Streamlit web UI. Connects the intent router, planner, composer, risk guard, and output components. |
| `planner.py`                   | High-level plan generator: infers plan type and time horizon, extracts goals and constraints, and outputs structured plan drafts. |
| `composer.py`                  | Scheduler / composer: converts plan drafts + user profile into daily routines; enforces time windows, rest intervals, and load control. |
| `verify.py`                    | Structural and safety verifier for both plans and schedules (format, missing fields, overlapping tasks, unrealistic intensity, etc.). |
| `act.py`                       | Action layer: transforms verified schedules into `.ics` calendar events and Markdown task lists. |
| `retrieval_autoload.py`        | Local knowledge base loader and TF-IDF retrieval module used by the planner and Q&A agents. |
| `evaluate.py`                  | Test harness and evaluation scripts for the risk guard, intent routing, verifier, and end-to-end flows. |
| `config/` (if present)         | Configuration files for models, paths, and default hyper-parameters. |
| `data/knowledge/` (if present) | Folder for local knowledge base documents (PDF, TXT, MD, etc.). |

---

## 4. Typical Usage Workflow

### 4.1 Start the Web App

    # 1. (Optional) activate your virtual environment
    # 2. Launch the Streamlit interface
    streamlit run application/FitForU_web.py

Open the URL shown in the terminal (usually `http://localhost:8501`) in your browser.

### 4.2 Configure the System

In the left sidebar:

1. Select the LLM model (served by Ollama or another backend).  
2. Adjust generation settings (temperature, max tokens, etc.).  
3. (Optional) Rebuild or refresh the local knowledge index if new documents are added.

### 4.3 Set Up Your User Profile

Use the profile panel to specify:

- typical wake / sleep times,  
- available time windows for exercise,  
- maximum daily workout duration,  
- existing injuries or forbidden movements,  
- language preference.

These fields are stored and used when generating and adjusting plans.

### 4.4 Make a Request

- **Small talk / generic chat**  
  Type directly; the Intent Router sends it to the base LLM with light safety checks.

- **Health Q&A**  
  Use the Q&A mode. If relevant knowledge exists in the local KB, the system retrieves and includes it in the prompt; otherwise, it answers conservatively.

- **New plan generation**  
  Describe your goal in natural language, e.g.:

  > “I want a 6-week beginner strength plan, 3 times per week, I only have dumbbells at home.”

  The pipeline will:

  1. Analyse intent and constraints.  
  2. Generate a high-level plan draft (modules, weeks, goals).  
  3. Schedule detailed sessions into your calendar windows.  
  4. Run risk & consistency checks.  
  5. Produce an exportable schedule.

### 4.5 Review & Export

- Inspect the generated plan structure and per-day tasks in the UI.  
- If it looks reasonable, click the export button to download:
  - an `.ics` calendar file, and/or  
  - a Markdown / text checklist.

You can then import the ICS file into Google Calendar, Outlook, Apple Calendar, etc.

### 4.6 Adjust an Existing Plan

If real life intervenes:

1. Open the **Plan Adjustment** tab.  
2. Mark specific tasks as finished / skipped.  
3. (Optionally) Update constraints (e.g. temporary illness, travel, changed availability).  
4. Run the **Reorganisation** function to rebuild the remaining schedule while preserving past history.

---

## 5. Installation & Environment

### 5.1 Prerequisites

- Python 3.8+  
- [Ollama](https://ollama.com/) installed and running (or another LLM backend compatible with the code)  
- Git  

### 5.2 Clone the Repository

    git clone <repository-url>
    cd FitForU   # replace with your actual project folder name

### 5.3 Create Virtual Environment (Recommended)

    python -m venv .venv
    source .venv/bin/activate  # on macOS / Linux
    # .venv\Scripts\activate   # on Windows

### 5.4 Install Dependencies

    pip install -r requirements.txt

If you use a different dependency management tool (e.g. Poetry, Conda), adapt this step accordingly.

### 5.5 Configure Environment (Optional)

If the project uses a `.env` file, create one and add settings such as:

    ICS_TZ=Asia/Shanghai
    OLLAMA_BASE_URL=http://localhost:11434

Adjust the timezone and model endpoint to your local setup.

---

## 6. Knowledge Base & Customisation

### 6.1 Adding Knowledge Documents

Put documents (TXT / MD / PDF etc.) into the configured knowledge directory (e.g. `data/knowledge/`).

Run the indexing step (from the UI or a script, depending on your final implementation).

New files will then be considered by `retrieval_autoload.py` for Q&A and planning.

### 6.2 Adding New Plan Types

To support additional plan types (e.g. marathon training, rehab for a specific injury):

- Extend plan templates and heuristics in `planner.py`.  
- Add corresponding scheduling rules (session length, frequency, recovery) in `composer.py`.  
- Update `verify.py` to check for new constraints and safety rules.

### 6.3 Extending Risk Rules

- Add new unsafe patterns or thresholds (e.g. too many high-intensity sessions per week).  
- Improve prompts or logic for the risk guard modules.  
- Add targeted test cases in `evaluate.py` to ensure the new rules work as expected.

---

## 7. Testing & Evaluation

To run the core tests (intent routing, risk guard, verifier, and selected end-to-end flows):

    python evaluate.py

You can extend the test suite with:

- additional high-risk prompts (self-harm, medication requests, etc.),  
- edge cases for scheduling (no available time, overlapping windows),  
- stress tests for long-horizon plans.

This helps keep the system stable as you modify prompts or logic.

---

## 8. Limitations & Future Work

Current limitations:

- Relies on the quality of the underlying LLM; hallucinations are mitigated but not fully eliminated.  
- Medical safety is handled conservatively but it is **not a medical device** and does not replace professional advice.  
- Scheduling assumes relatively regular daily routines; highly irregular schedules may require manual adjustment.

Possible future improvements:

- Integration with real fitness trackers and health data.  
- More advanced retrieval (embeddings-based RAG instead of simple TF-IDF).  
- Web or mobile front-ends beyond Streamlit.  
- Personalised long-term progress tracking and analytics dashboards.

---

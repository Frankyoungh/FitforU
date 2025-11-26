
# FitForU-An Intelligent Health Assistant Agent System

## Project Overview
This system is a specialized tool for generating and managing plans in health, fitness, nutrition, and related domains. It automatically creates structured plan drafts based on user input, configuration settings, and historical preferences, while supporting full lifecycle functions including plan verification, schedule arrangement, and export. The goal is to help users efficiently plan health-related activities.

## Core Features
1. **Intelligent Plan Draft Generation**  
   Automatically generates structured plan drafts (including plan type, time horizon, time windows, and module content) based on user input (e.g., fitness goals, dietary needs), configuration parameters, and memory data (e.g., personal preferences). Supports multiple plan types (fitness, nutrition, rehabilitation, lifestyle, etc.) and automatically infers user needs through keywords.

2. **Plan Verification & Validation**  
   Performs static checks on generated plan drafts to ensure structural validity (e.g., module completeness, time range validity, tag standardization), preventing invalid or erroneous plan content.

3. **Personalized Schedule Arrangement**  
   Converts plan drafts into executable daily schedules. Intelligently distributes daily activities based on personal available time slots, daily duration limits, and muscle group training intervals to ensure plan feasibility.

4. **Multi-Format Export**  
   Supports exporting scheduled plans to ICS calendar format (compatible with mainstream calendar apps) or Markdown checklist format for easy viewing and execution.

5. **Knowledge Base Retrieval**  
   Automatically loads local knowledge base files (supports Markdown, TXT, PDF, etc.) and implements keyword retrieval via TF-IDF algorithm to provide knowledge support for plan generation and risk verification.

## Core Module Description
| Module File | Main Functions |
|-------------|----------------|
| `planner.py` | Generates plan drafts, including inferring plan types, determining time horizons, extracting keywords, and constructing basic modules. |
| `verify.py` | Validates the legality of plan drafts, checking module completeness, time format, tag validity, etc. |
| `composer.py` | Arranges plans based on personal profiles, handling time window priorities, daily duration limits, muscle group intervals, and other rules. |
| `act.py` | Converts scheduled plans into actionable items and supports export to ICS calendar or Markdown checklist. |
| `retrieval_autoload.py` | Loads local knowledge base files and provides TF-IDF-based keyword retrieval functionality. |
| `evaluate.py` | Tests the functional correctness of plan generation and verification modules. |

## Usage Workflow
1. **Input & Configuration**: Users provide requirement text (e.g., "Create a weekly fitness plan") and related configurations (e.g., time range, preferred time windows).  
2. **Draft Generation**: The system generates an initial draft with plan type and module content via `planner.py`.  
3. **Draft Verification**: `verify.py` checks the draft's legality to ensure no structural errors.  
4. **Personalized Scheduling**: `composer.py` adjusts the schedule based on personal profiles to align with time constraints and preferences.  
5. **Export & Execution**: Export the final plan to calendar or checklist format via `act.py` for user execution.

## Technical Features
- **Configurable Rules**: Plan generation logic is based on explicit rules, supporting parameter adjustments (e.g., maximum daily duration, time window priorities).  
- **Multi-Source Information Fusion**: Integrates user input, configuration parameters, memory preferences, and knowledge base content to enhance plan rationality.  
- **Lightweight & Extensible**: Adopts simple TF-IDF retrieval and rule engines with no complex dependencies, facilitating expansion of new plan types or data sources.  
- **Multi-Format Compatibility**: Supports multiple knowledge base file formats and plan export formats to adapt to different usage scenarios.

## Dependencies
- Python 3.8+
- Core Libraries: `streamlit` (UI), `numpy` (numerical processing), `pandas` (data handling), `python-dotenv` (environment configuration), `ics` (ICS file generation), `markdown` (Markdown processing)

## Installation & Setup
1. Clone the repository:  
   ```bash
   git clone <repository-url>
   cd plan-management-system
   ```
2. Install dependencies:  
   ```bash
   pip install -r requirements.txt
   ```
3. Configure environment variables (optional):  
   Create a `.env` file to set custom configurations (e.g., `ICS_TZ=Asia/Shanghai` for time zone settings).
4. Run the application:  
   ```bash
   streamlit run application/FitForU_web.py
   ```

## Notes
- Ensure local knowledge base files are placed in the specified directory (default: `data/knowledge/`) for retrieval functionality.  
- For custom plan types, extend the rule sets in `planner.py` and `verify.py`.  
- Exported ICS files can be imported into Google Calendar, Outlook, or other calendar applications.

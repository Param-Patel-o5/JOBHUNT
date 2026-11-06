# JobHunt OS: LangGraph Autonomous Outreach Pipeline

> **An autonomous, multi-agent AI pipeline built on LangGraph that ingests, filters, company-evaluates, and pairs developer portfolios with open engineering roles—featuring two-stage cold outreach generation and a high-velocity triage dashboard.**

---

## ⚡ What is JobHunt OS?

Job hunting in AI and software engineering is fundamentally broken: engineers manually scan dozens of boards, wade through contract/RLHF traps, fight quota limits, and send generic messages that get ignored.

**JobHunt OS** is an agentic, production-grade intelligence layer designed to automate the entire top-of-funnel discovery and personalized outreach workflow:

1. **Scrapes** across 4 federated channels (remote boards, direct ATS feeds, job aggregators, and search dorking).
2. **Filters** ruthlessly using a deterministic 7-gate filter before spending a single LLM token.
3. **Evaluates** company quality and compensation bars (>= 15 LPA) in batched Gemini LLM calls with SQLite caching.
4. **Discovers** current employees (alumni, tech leads, recruiters) using OSINT search dorking while strictly filtering out ex-employees.
5. **Drafts** two-stage human networking packages: a respectful mentor-framed connection note (≤ 260 chars) and an elevator-pitch referral DM (≤ 95 words).
6. **Delivers** everything into a tactile Linear/Notion-style Streamlit dashboard for rapid morning triage.

---

## 🏗️ Architecture & Core Features

```
[Channel 1: WWR RSS]     [Channel 2: Himalayas API]   [Channel 3: Search Dorking]   [Channel 4: JobSpy]
         \                         |                         |                         /
          \                        |                         |                        /
           +-----------------------+-------------------------+-----------------------+
                                   |
                                   v
                       +-----------------------+
                       |    1. Scrape Node     | --> Parallel Jina Reader JD Hydration
                       +-----------------------+
                                   |
                                   v
                       +-----------------------+
                       |  2. Gatekeeper Node   | --> Deterministic 7-Gate Zero-Cost Filter
                       +-----------------------+
                                   |
                                   v
                       +-----------------------+
                       | 3. Company Intel Node | --> Batched Gemini Eval + SQLite Caching
                       +-----------------------+
                                   |
                                   v
                       +-----------------------+
                       |  4. Enrichment Node   | --> Matcher + People Finder + Drafter
                       +-----------------------+
                                   |
                                   v
                       +-----------------------+
                       |  5. Persistence Node  | --> SQLite Atomic Storage (jobs table)
                       +-----------------------+
                                   |
                                   v
                       +-----------------------+
                       | Streamlit Triage App  | --> Flashcard Queue + Tracker + Follow-Ups
                       +-----------------------+
```

### 1. 4-Channel Federated Ingestion
- **Channel 1 (WeWorkRemotely RSS):** Fetches fresh feeds across AI, Machine Learning, and Backend categories.
- **Channel 2 (Himalayas Job Board API):** Queries live verified remote engineering listings.
- **Channel 3 (Dual-Engine ATS Dorking):** Targets Greenhouse, Lever, and Ashby postings via Tavily Search with automatic fallback to DuckDuckGo and concurrent Jina Reader (`r.jina.ai`) hydration.
- **Channel 4 (JobSpy Multi-Aggregator):** Ingests structured postings from LinkedIn, Indeed, and Google Jobs with headless resilience.

### 2. Deterministic Gatekeeper (Zero-LLM Cost)
Eliminates junk and traps before any LLM invocations:
- **Deduplication:** Hash-based and `(company + role)` checks against SQLite.
- **RLHF & Freelance Traps:** Drops coding-task gigs, prompt evaluation tasks, and crowd-worker platforms (e.g. Outlier, Alignerr, DataAnnotation, Askable).
- **Agency Blacklists:** Drops staffing firms and talent brokers (e.g. Crossover, Turing, Revature).
- **Seniority & YoE Guards:** Enforces candidate graduation limits (max 2 YoE, rejects Staff/Principal/Lead titles).
- **Geo-Fencing:** Filters for India or global remote-friendly roles.

### 3. Batched LLM Company Evaluator & Multi-Key Router
- **Multi-Account Round-Robin Pool:** Cycles multiple Google AI Studio keys to maximize free tier rate limits (15 RPM / 500 RPD per key).
- **Automatic 503 & Rate-Limit Failover:** Gracefully catches service overload and rate limits, instantly retrying on alternate models (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-2.5-flash`).
- **SQLite Intel Cache:** Evaluates company business model, scale, and entry CTC in batches of up to 8 companies—caching results so no company is ever evaluated twice.

### 4. OSINT People Finder & Two-Stage Drafter
- **Ex-Employee Filtering:** Distinguishes current employees from alumni who left for other companies (rejecting `"ex-company"` or `"previously at"` false positives).
- **Journey Context Extraction:** Extracts BITS Pilani campus, graduation batch, and engineering domains directly from LinkedIn search snippets.
- **Two-Stage Human Networking:**
  - **Stage 1 (Connection Note ≤ 260 chars):** Mentor/advice frame without asking for a referral.
  - **Stage 2 (Post-Connection DM ≤ 95 words):** Connects the candidate's PyPI-published project to the role, asking for a referral with zero friction (offers resume PDF + Job ID).
- **HR Email Discovery:** Regex-extracts careers emails from JDs or derives clean domain patterns (`careers@{domain}`).

### 5. Streamlit Triage Dashboard (`app.py`)
- **Warm Paper & Ink Aesthetic:** Clean Alabaster `#F7F7F5` layout, dark ink `#111827`, and zero neon slop.
- **Flashcard Focus Mode:** One job at a time with instant keyboard navigation and 1-click copy code boxes (`wrap_lines=True`).
- **Interactive 8-Column Tracker:** Live spreadsheet editor for tracking status transitions:
  `NEW` → `CONNECT_SENT` → `ASKED_REFERRAL` → `APPLIED_VIA_REFERRAL`
- **48-Hour Follow-Up Queue:** Alerts when referrals have been pending for ≥ 48 hours with pre-drafted 25-word follow-up bumps.

---

## 🛠️ Tech Stack

- **Orchestration:** [LangGraph](https://github.com/langchain-ai/langgraph), [LangChain Core](https://github.com/langchain-ai/langchain)
- **Foundation Models:** Google Gemini 3.5 Flash Lite / 2.5 Flash via `langchain-google-genai`
- **Search & Dorking:** [Tavily Python API](https://tavily.com/), [DuckDuckGo Search](https://github.com/deedy5/duckduckgo_search), [Jina Reader](https://jina.ai/reader/)
- **UI & Dashboard:** [Streamlit](https://streamlit.io/) (2026-compliant `width="stretch"` layout)
- **Persistence:** SQLite3 (WAL-mode, zero-latency local database)
- **Validation:** [Pydantic v2](https://docs.pydantic.dev/)

---

## 🚀 Quickstart & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/Param-Patel-o5/JOBHUNT.git
cd JOBHUNT
```

### 2. Set Up a Virtual Environment
```bash
python -m venv .venv

# On Linux / macOS:
source .venv/bin/activate

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Fill in your API keys in `.env`:
```env
# Google AI Studio API Keys (Add 1 or more comma-separated keys for round-robin rotation)
GEMINI_API_KEYS=your_key_1,your_key_2,your_key_3
GOOGLE_API_KEY=your_key_1

# Search Engine API (Optional, falls back to DuckDuckGo automatically)
TAVILY_API_KEY=your_tavily_key
```

### 5. Configure Your Candidate Profile
Edit `config/profile_context.yaml` with your background, target roles, location preferences, and core project arsenal:
```yaml
candidate:
  name: "Your Name"
  university: "Your University"
  graduation_year: 2027
  portfolio_url: "https://yourportfolio.dev"
  min_ctc_lpa: 15

project_arsenal:
  - id: "your_project"
    name: "Project Name"
    one_liner: "Plain English summary of what you built and measured."
    best_for_jd_keywords: ["langgraph", "rag", "agents", "python"]
```

### 6. Initialize Database & Run Full Test Suite
```bash
# Initialize SQLite database schema
python -c "from src.db import init_db; init_db()"

# Run full system verification tests in isolated sandbox
python tests/test_full_system.py
```

### 7. Launch the Dashboard
```bash
streamlit run app.py
```
Open [http://localhost:8501](http://localhost:8501) in your browser. Click **Fetch New Jobs** to trigger the end-to-end ingestion and enrichment pipeline!

---

## 📂 Project Structure

```
JOBHUNT/
├── .streamlit/
│   └── config.toml             # Light mode enforcement & typography
├── config/
│   └── profile_context.yaml    # Candidate context, project arsenal & hard filters
├── data/                       # Local SQLite storage (gitignored)
│   └── job_hunt.db
├── scripts/
│   └── backfill_jobs.py        # Migration & backfill utility
├── src/
│   ├── models.py               # Pydantic v2 schemas & LangGraph state
│   ├── db.py                   # SQLite schema, queries, migrations & tracking
│   ├── llm_router.py           # Multi-key pool rotation & model failover
│   ├── graph.py                # LangGraph StateGraph pipeline compilation
│   └── nodes/
│       ├── scrapers.py         # 4-Channel federated ingestion & Jina hydration
│       ├── gatekeeper.py       # Deterministic 7-gate zero-cost filter
│       ├── company_intel.py    # Batched company evaluation & SQLite caching
│       ├── matcher.py          # Project alignment & copy-paste resume bullet tailor
│       ├── people_finder.py    # OSINT contact discovery & HR email finder
│       └── drafter.py          # Two-stage human outreach generation
├── tests/
│   ├── test_ingestion_pipeline.py
│   ├── test_intelligence_layer.py
│   ├── test_people_and_outreach.py
│   └── test_full_system.py
├── .env.example
├── .gitignore
├── app.py                      # Streamlit triage dashboard & Excel tracker
├── ARCHITECTURE.md             # In-depth technical architecture breakdown
├── requirements.txt            # Pinned production dependencies
└── README.md
```

---

## 📄 License

MIT License. Feel free to fork, adapt, and run your own autonomous job hunt pipeline!

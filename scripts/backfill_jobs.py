"""
One-off Migration & Backfill Script for data/job_hunt.db.

Backfills existing rows with:
  1. Clean current-employee contacts (ex-employees filtered out, journey context captured).
  2. Discovered hr_email and default referrer_name.
  3. Plain-English 3-4 sentence company overview in company_summary.
  4. Concise 4-5 bullet point role requirements in jd_summary_json.
  5. Tailored plain-English winning hook and 2 copy-pasteable first-person resume bullets.
  6. Two-stage human networking outreach packages (Mentor Connection Note <= 260 chars + Plain-English Low-Hassle Referral DM <= 95 words).
"""

import sys
import os
import json
import sqlite3
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import (
    JobPosting,
    CompanyIntel,
    MatchAndTailorResult,
    ContactPerson,
    OutreachPackage,
)
from src.nodes.people_finder import (
    find_contacts_for_company,
    find_hr_email_for_company,
    clear_contacts_cache,
)
from src.nodes.drafter import generate_outreach_for_job
from src.db import DB_PATH, init_db

PORTFOLIO_URL = "https://parampatel-ai.vercel.app"

# Plain-English company knowledge base for high-fidelity backfill
COMPANY_DEEP_INTEL = {
    "netapp": {
        "summary": "NetApp is a global leader in intelligent cloud data infrastructure and storage management solutions. Serving thousands of enterprise customers worldwide, they operate at multi-billion dollar public scale. Their engineering teams focus on high-throughput storage systems, distributed data fabrics, and adapting agentic AI pipelines for enterprise data management.",
        "stage": "Public MNC (NASDAQ: NTAP)",
        "ctc": 24.0,
        "hr_email": "careers@netapp.com",
    },
    "databricks": {
        "summary": "Databricks provides the industry-leading unified Lakehouse platform combining data engineering, business intelligence, and generative AI. They serve over 10,000 global enterprise customers including Shell, Comcast, and AT&T at a $43B+ valuation. Their engineering teams build distributed Spark runtimes, Mosaic AI foundation model infrastructure, and MLflow serving pipelines.",
        "stage": "Pre-IPO ($43B Valuation)",
        "ctc": 35.0,
        "hr_email": "careers@databricks.com (pattern)",
    },
    "perplexity": {
        "summary": "Perplexity is an AI-powered conversational search engine delivering conversational answers with cited real-time web sources. They serve millions of daily active users and top enterprises at a multi-billion dollar valuation backed by IVP and NVIDIA. Their core engineering team builds high-throughput real-time web crawlers, hybrid search indexers, and low-latency LLM inference architectures.",
        "stage": "Series C ($9B Valuation)",
        "ctc": 32.0,
        "hr_email": "talent@perplexity.ai (pattern)",
    },
    "elevenlabs": {
        "summary": "ElevenLabs is the leading generative AI voice research and audio platform delivering realistic text-to-speech, voice cloning, and conversational audio agents. They power audio workflows for major publishers, game studios, and millions of creators at a $3B+ unicorn valuation. Their research and engineering teams train multi-modal audio foundation models and optimize low-latency real-time voice inference engines.",
        "stage": "Series B Unicorn ($3B Valuation)",
        "ctc": 30.0,
        "hr_email": "careers@elevenlabs.io (pattern)",
    },
    "walmart global tech india": {
        "summary": "Walmart Global Tech India builds enterprise technology that powers Walmart's global retail network of over 10,500 stores and eCommerce platforms. Operating at Fortune 1 scale, their teams process millions of transactions per second. Their engineering divisions develop predictive supply-chain optimization, automated customer analytics, and large-scale recommendation systems.",
        "stage": "Global Enterprise MNC",
        "ctc": 22.0,
        "hr_email": "careers@walmart.com",
    },
    "aidaptive": {
        "summary": "Aidaptive is an eCommerce AI platform delivering automated personalization, predictive pricing, and product recommendation engines. They serve fast-growing mid-market and enterprise online merchants to maximize revenue conversion. Their engineering team focuses on real-time event stream processing, tabular machine learning models, and automated customer segment prediction.",
        "stage": "Series A ($12M+ Funded)",
        "ctc": 18.0,
        "hr_email": "careers@aidaptive.com (pattern)",
    },
    "ohm": {
        "summary": "Ohm is an AI-driven energy intelligence and smart battery analytics startup backed by top climate investors and Y Combinator. They help commercial and utility clean energy providers forecast power consumption and battery degradation. Their technical team builds physics-informed ML pipelines, time-series forecasting models, and IoT telemetry ingestion systems.",
        "stage": "Seed ($3.5M YC Backed)",
        "ctc": 18.0,
        "hr_email": "careers@ohm.energy (pattern)",
    },
    "sony india software centre": {
        "summary": "Sony India Software Centre is Sony Corporation's central software engineering hub developing next-generation multimedia, gaming, and AI technologies. They build software for PlayStation platforms, smart cameras, and consumer entertainment products. Their engineering teams focus on generative AI multimedia pipelines, computer vision algorithms, and embedded edge AI acceleration.",
        "stage": "Public MNC (Sony Group)",
        "ctc": 18.5,
        "hr_email": "careers@sony.com",
    },
    "mobility global": {
        "summary": "Mobility Global is an intelligent transportation and automotive logistics technology firm developing autonomous fleet monitoring and predictive routing systems. They serve commercial transport operators and urban transit authorities across emerging markets. Their engineering teams specialize in spatial tracking algorithms, route optimization engines, and vehicle sensor data streaming.",
        "stage": "Growth Stage",
        "ctc": 16.0,
        "hr_email": "careers@mobilityglobal.com (pattern)",
    },
}

# Role requirement templates
ROLE_REQUIREMENTS_TEMPLATES = {
    "ai engineer": [
        "Design and deploy production-grade LLM workflows, RAG pipelines, and conversational AI agents.",
        "Optimize low-latency model inference, prompt caching, and evaluation metrics.",
        "Build scalable Python microservices integrated with vector databases (ChromaDB, Pinecone, or Milvus).",
        "Implement automated guardrails, latency monitoring, and trace observability.",
        "Collaborate with backend engineers to integrate AI capabilities into customer-facing products."
    ],
    "machine learning engineer": [
        "Develop, train, and validate supervised and unsupervised machine learning models on high-volume datasets.",
        "Build feature engineering pipelines and end-to-end model evaluation suites.",
        "Package and deploy models as production REST/gRPC inference APIs with Docker and Kubernetes.",
        "Monitor model drift, accuracy degradation, and data pipeline reliability in production.",
        "Strong proficiency in Python, PyTorch/TensorFlow, scikit-learn, and SQL data modeling."
    ],
    "data scientist": [
        "Analyze complex enterprise datasets to extract predictive patterns, user segments, and business insights.",
        "Develop statistical forecasting and tabular machine learning models for core business metrics.",
        "Design rigorous A/B experiments and hypothesis testing frameworks to measure model impact.",
        "Communicate analytical findings clearly through executive dashboards and data stories.",
        "Proficiency in Python/R, SQL, scikit-learn, XGBoost, and statistical modeling."
    ],
    "research engineer": [
        "Conduct empirical experiments on model architectures, fine-tuning techniques, and synthetic data generation.",
        "Optimize multi-GPU distributed training clusters and high-throughput data loading pipelines.",
        "Benchmark frontier model capabilities and implement novel algorithms from recent research papers.",
        "Write clean, high-performance C++ and Python code for low-latency inference runtimes.",
        "Collaborate with product teams to transition cutting-edge research into production APIs."
    ],
    "ai strategist": [
        "Bridge executive business strategy and generative AI capabilities for enterprise financial clients.",
        "Scope high-ROI AI use cases across risk management, regulatory reporting, and customer workflows.",
        "Evaluate LLM vendor offerings, data governance policies, and deployment architectures.",
        "Collaborate with enterprise engineering leaders to design phased AI adoption roadmaps.",
        "Deep understanding of financial compliance, enterprise security, and AI system design."
    ],
}


def get_role_bullets(role: str) -> list:
    role_lower = role.lower()
    for key, bullets in ROLE_REQUIREMENTS_TEMPLATES.items():
        if key in role_lower:
            return bullets
    return ROLE_REQUIREMENTS_TEMPLATES["ai engineer"]


def backfill():
    print("=" * 70)
    print("Starting Comprehensive Backfill on data/job_hunt.db")
    print("=" * 70)

    init_db()
    clear_contacts_cache()

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM jobs")
        jobs = cur.fetchall()

    print(f"Loaded {len(jobs)} jobs from database.")

    updated_count = 0
    with sqlite3.connect(DB_PATH) as conn:
        for row in jobs:
            job_id = row["job_id"]
            company = row["company"].strip()
            role = row["role"].strip()
            location = row["location"] or "Remote / India"
            job_url = row["job_url"]
            source = row["source"] or "Direct"
            c_key = company.lower()

            print(f"\nProcessing [{job_id}] {company} - {role}...")

            # 1. Company Intel
            info = COMPANY_DEEP_INTEL.get(c_key, {})
            company_summary = info.get(
                "summary",
                f"{company} is an established technology company developing software and machine learning infrastructure. Their engineering teams focus on building high-reliability products, scalable backend services, and modern data-driven architectures."
            )
            stage = info.get("stage", row["company_stage"] or "Growth")
            ctc = float(info.get("ctc", row["est_ctc_lpa"] or 18.0))

            # 2. HR Email
            hr_email = row["hr_email"]
            if not hr_email:
                hr_email = info.get("hr_email") or find_hr_email_for_company(company, job_url, row["jd_text"] or "")

            # 3. Discovered Contacts (with ex-employee filter)
            contacts = find_contacts_for_company(company, role)
            referrer_name = ", ".join(c.name for c in contacts) if contacts else (row["referrer_name"] or "")

            # 4. Role requirements summary
            jd_bullets = get_role_bullets(role)

            # 5. Selected Project & Winning Hook
            role_lower = role.lower()
            if any(k in role_lower for k in ["fintech", "finance", "risk", "credit", "compliance"]):
                selected_proj = "fairtrace"
                hook = f"Built a credit-risk ML pipeline balancing high predictive accuracy (0.741 AUC) with regulatory fairness, directly applicable to {company}'s financial modeling requirements."
                bullets = [
                    f"Engineered tabular ML pipelines using XGBoost and SHAP for regulatory compliance at {company}.",
                    f"Optimized feature engineering pipelines achieving 0.741 AUC with strict fairness constraints."
                ]
            elif any(k in role_lower for k in ["c++", "systems", "crawler", "infrastructure", "inference", "low-latency"]):
                selected_proj = "lidar_parser"
                hook = f"Authored a first-author paper on a high-speed C++/Python data converter processing 2.08M points/sec, aligning directly with {company}'s low-latency systems and throughput goals."
                bullets = [
                    f"Optimized C++ and Python data ingestion runtimes processing 2.08M items/sec on consumer hardware.",
                    f"Engineered memory-mapped binary parsing pipelines for low-latency streaming infrastructure at {company}."
                ]
            elif any(k in role_lower for k in ["search", "rag", "retrieval", "nlp", "document"]):
                selected_proj = "tempus_rag"
                hook = f"Built a financial search engine over 5 years of SEC filings combining keyword and vector search (87.4% accuracy), matching {company}'s retrieval and precision needs."
                bullets = [
                    f"Engineered hybrid search pipelines combining BM25 keyword matching and ChromaDB vector embeddings for {company}.",
                    f"Implemented reciprocal rank fusion (RRF) re-ranking achieving 0.8744 retrieval accuracy on unstructured text."
                ]
            else:
                selected_proj = "agent_diagnostician"
                hook = f"Published an open-source PyPI tool that automatically tracks and debugs why multi-agent LangGraph workflows fail, directly matching {company}'s agent reliability requirements."
                bullets = [
                    f"Developed and published an open-source Python diagnostic library on PyPI for tracing and debugging multi-agent AI failures.",
                    f"Integrated automated guardrails and execution-trace telemetry into LangGraph pipelines to eliminate production agent loops."
                ]

            # 6. Draft 2-Stage Outreach Packages
            drafts = []
            if contacts:
                for c in contacts:
                    c_first = c.name.split()[0]
                    # Stage 1: Connection Note <= 260 chars (Mentor frame, NO referral ask)
                    if c.tier == "1_ALUMNI":
                        note = (
                            f"Hi {c_first}, fellow BITSian here (2027 batch). Came across your profile while looking into "
                            f"{company}'s AI work. Would love to connect and learn a bit about your engineering journey from BITS to {company}!"
                        )
                    else:
                        note = (
                            f"Hi {c_first}, came across your work in AI engineering at {company}. As a 2027 graduate from BITS Pilani, "
                            f"I would love to connect and follow your team's engineering updates!"
                        )
                    if len(note) > 260:
                        note = note[:257] + "..."

                    # Stage 2: Post-Connection DM <= 95 words (Plain English Proof + Low-Hassle Referral Ask)
                    dm = (
                        f"Hi {c_first}, thank you for connecting! I am applying for the {role} position at {company} ({job_url}). "
                        f"{hook} If you feel my profile is a fit, I'd be really grateful for a referral—happy to send my resume PDF "
                        f"and Job ID so it takes zero hassle. Either way, I would love any advice you have for a junior entering this space! "
                        f"My work: {PORTFOLIO_URL}"
                    )
                    words = dm.split()
                    if len(words) > 95:
                        dm = " ".join(words[:94]) + f". My work: {PORTFOLIO_URL}"

                    pkg = OutreachPackage(
                        contact_name=c.name,
                        contact_tier=c.tier,
                        linkedin_url=c.linkedin_url,
                        connection_note_300_chars=note,
                        full_dm_under_95_words=dm,
                    )
                    drafts.append(pkg)

            fallback_note = (
                f"Hi {company} team,\n\n"
                f"I am Param Patel, a 2027 graduate from BITS Pilani applying for the {role} position. "
                f"{hook} My technical projects, benchmarks, and research code are available at {PORTFOLIO_URL}. "
                f"I would welcome the opportunity to discuss how my hands-on AI engineering background directly aligns with your team's goals."
            )

            # Persist back into SQLite
            conn.execute(
                """
                UPDATE jobs 
                SET company_summary = ?,
                    company_stage = ?,
                    est_ctc_lpa = ?,
                    hr_email = ?,
                    referrer_name = ?,
                    jd_summary_json = ?,
                    selected_project = ?,
                    winning_hook = ?,
                    resume_tweaks_json = ?,
                    contacts_json = ?,
                    outreach_drafts_json = ?,
                    fallback_note = ?
                WHERE job_id = ?
                """,
                (
                    company_summary,
                    stage,
                    ctc,
                    hr_email,
                    referrer_name,
                    json.dumps(jd_bullets),
                    selected_proj,
                    hook,
                    json.dumps(bullets),
                    json.dumps([c.model_dump() for c in contacts]),
                    json.dumps([d.model_dump() for d in drafts]),
                    fallback_note,
                    job_id,
                ),
            )
            updated_count += 1

        conn.commit()

    print("\n" + "=" * 70)
    print(f"SUCCESS: Successfully backfilled {updated_count} jobs in {DB_PATH}!")
    print("=" * 70)


if __name__ == "__main__":
    backfill()


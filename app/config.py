"""Central configuration for Mini Charlotte AI.

Everything defaults to a local, zero-credential demo: data ships in the repo,
the local Ollama model is the default explain provider, and the Anthropic
cloud path only activates when a caller supplies an API key on the request
itself (never read from disk/env on the server side).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RUNTIME_DIR = BASE_DIR / "runtime"
RUNTIME_DIR.mkdir(exist_ok=True)

CHAINS_PATH = DATA_DIR / "chains.jsonl"
ALERTS_PATH = DATA_DIR / "alerts_representatives.jsonl"
LABELS_PATH = DATA_DIR / "labels.csv"
EVALUATION_PATH = DATA_DIR / "evaluation.json"

FEEDBACK_STORE_PATH = RUNTIME_DIR / "feedback_store.json"
LLM_CACHE_PATH = RUNTIME_DIR / "llm_cache.json"
LIVE_CHAINS_PATH = RUNTIME_DIR / "live_chains.jsonl"   # ingested incidents (gitignored)
LIVE_ALERTS_PATH = RUNTIME_DIR / "live_alerts.jsonl"   # ingested alerts (gitignored)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-r1:8b")
OLLAMA_MODEL_ALT = os.getenv("OLLAMA_MODEL_ALT", "gpt-oss:20b")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
KIMI_MODEL = os.getenv("KIMI_MODEL", "k3-256k")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1")

HOST = "127.0.0.1"  # localhost only — never binds to a public interface
PORT = int(os.getenv("PORT", "8713"))

# Shared-secret gate for POST /api/ingest. Empty (the local default) means
# the endpoint is open — fine for judging on localhost. Set this before
# deploying anywhere reachable publicly (e.g. Azure App Service), otherwise
# /api/ingest is an unauthenticated public write path.
INGEST_API_KEY = os.getenv("INGEST_API_KEY", "")

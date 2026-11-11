#!/bin/bash
# ─────────────────────────────────────────────
#  SmartSmith — start the FastAPI backend
#  Run from the repo root: bash start.sh
# ─────────────────────────────────────────────

set -e
cd "$(dirname "$0")"

# ── 1. Pick the right python ─────────────────
PYTHON=""

# Prefer an active virtualenv, then a repo-local .venv, before falling
# back to any system Python on PATH.
if [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
  PYTHON="$VIRTUAL_ENV/bin/python"
elif [ -x ".venv/bin/python" ]; then
  PYTHON="$(pwd)/.venv/bin/python"
else
  for cmd in python python3 python3.12 python3.11 python3.10; do
    if command -v "$cmd" &>/dev/null; then
      PYTHON="$(command -v "$cmd")"
      break
    fi
  done
fi

if [ -z "$PYTHON" ]; then
  echo ""
  echo "❌  Python not found."
  echo "    Install it first:  brew install python   (macOS)"
  echo "    Then re-run:       bash start.sh"
  exit 1
fi

echo "✅  Using Python: $($PYTHON --version)"

# ── 2. Check .env exists ─────────────────────
if [ ! -f ".env" ]; then
  echo ""
  echo "❌  .env file not found in $(pwd)"
  echo "    Create one with at minimum:"
  echo ""
  echo "      OPENAI_API_KEY=sk-..."
  echo "      SUPABASE_URL=https://xxx.supabase.co"
  echo "      SUPABASE_KEY=..."
  echo "      TAVILY_API_KEY=tvly-...   # optional"
  echo ""
  exit 1
fi

# Verify the three required keys are non-empty
missing=()
source_env() {
  set -a; source .env; set +a
}
source_env 2>/dev/null || true

[ -z "$OPENAI_API_KEY" ]  && missing+=("OPENAI_API_KEY")
[ -z "$SUPABASE_URL" ]    && missing+=("SUPABASE_URL")
[ -z "$SUPABASE_KEY" ]    && missing+=("SUPABASE_KEY")

if [ ${#missing[@]} -gt 0 ]; then
  echo ""
  echo "❌  Missing required keys in .env:"
  for key in "${missing[@]}"; do
    echo "      - $key"
  done
  echo ""
  exit 1
fi

echo "✅  .env looks good"

# ── 3. Install / update dependencies ─────────
echo ""
echo "📦  Installing Python dependencies..."
if ! "$PYTHON" -m pip install -r requirements.txt --quiet; then
  echo ""
  echo "❌  Dependency install failed for:"
  echo "    $PYTHON"
  echo ""
  echo "    SmartSmith works best from a virtual environment."
  echo "    Try one of these, then re-run bash start.sh:"
  echo ""
  echo "      python3 -m venv .venv"
  echo "      source .venv/bin/activate"
  echo ""
  echo "    Or install directly with the chosen interpreter:"
  echo ""
  echo "      \"$PYTHON\" -m pip install -r requirements.txt"
  echo ""
  exit 1
fi

# ── 4. Start uvicorn ─────────────────────────
echo ""
echo "🚀  Starting SmartSmith backend at http://localhost:8000"
echo "    Health check → http://localhost:8000/health"
echo "    Press Ctrl+C to stop."
echo ""

$PYTHON -m uvicorn server:app --reload --port 8000

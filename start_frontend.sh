#!/bin/bash
# ─────────────────────────────────────────────
#  SmartSmith — start the React frontend
#  Run from the repo root: bash start_frontend.sh
# ─────────────────────────────────────────────

set -e
cd "$(dirname "$0")/frontend"

# ── 1. Check node / npm ───────────────────────
if ! command -v node &>/dev/null; then
  echo ""
  echo "❌  Node.js not found."
  echo "    Install it:  brew install node   (macOS)"
  echo "               or https://nodejs.org"
  exit 1
fi

if ! command -v npm &>/dev/null; then
  echo ""
  echo "❌  npm not found (usually ships with Node)."
  echo "    Re-install Node from https://nodejs.org"
  exit 1
fi

echo "✅  Node $(node --version) / npm $(npm --version)"

# ── 2. Install deps if needed ─────────────────
if [ ! -d "node_modules" ]; then
  echo ""
  echo "📦  Running npm install..."
  npm install
fi

# ── 3. Start dev server ───────────────────────
echo ""
echo "🚀  Starting SmartSmith frontend at http://localhost:3000"
echo "    Make sure the backend is running in another terminal (bash start.sh)"
echo "    Press Ctrl+C to stop."
echo ""

npm start

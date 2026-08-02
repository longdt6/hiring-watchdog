#!/usr/bin/env bash
# ============================================================
# Hiring Watchdog — Daily Crawl Script
# Chạy mỗi sáng qua cron: 0 8 * * * /path/to/run_daily.sh
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/daily-$(date +%Y-%m-%d).log"

# Redirect all output to log file + terminal
exec > >(tee -a "$LOG_FILE") 2>&1

echo "============================================================"
echo "  Hiring Watchdog — Daily Crawl"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo ""

# ── Activate virtual environment ──────────────────────────────
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
    echo "✅ Virtual environment activated"
else
    echo "❌ Virtual environment not found at .venv/"
    echo "   Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && playwright install chromium"
    exit 1
fi

# ── Phase 1: Crawl ITViec ─────────────────────────────────────
echo ""
echo "─── Crawling ITViec ───"
python crawlers/itviec.py --days 1

# ── Phase 2: Crawl VietnamWorks ─────────────────────────────
echo ""
echo "─── Crawling VietnamWorks ───"
python crawlers/vietnamworks.py --days 1

# ── Phase 3: Merge + Dedup ─────────────────────────────────
echo ""
echo "─── Merging sources ───"
python pipeline/merge.py

# ── Phase 4: Detection Engine ───────────────────────────────
echo ""
echo "─── Running Detection Engine ───"
python detection/fusion.py

# ── Health check ──────────────────────────────────────────────
TODAY=$(date +%Y-%m-%d)
ITVIEC_FILE="data/raw/$TODAY/itviec.json"
VNW_FILE="data/raw/$TODAY/vietnamworks.json"
PROCESSED_FILE="data/processed/$TODAY.json"

ITVIEC_COUNT=0
VNW_COUNT=0
PROCESSED_COUNT=0

if [ -f "$ITVIEC_FILE" ]; then
    ITVIEC_COUNT=$(python -c "import json; print(len(json.load(open('$ITVIEC_FILE'))))" 2>/dev/null || echo "0")
fi

if [ -f "$VNW_FILE" ]; then
    VNW_COUNT=$(python -c "import json; print(len(json.load(open('$VNW_FILE'))))" 2>/dev/null || echo "0")
fi

if [ -f "$PROCESSED_FILE" ]; then
    PROCESSED_COUNT=$(python -c "import json; print(len(json.load(open('$PROCESSED_FILE'))))" 2>/dev/null || echo "0")
fi

echo ""
echo "============================================================"
echo "  ✅ Done — $(date '+%Y-%m-%d %H:%M:%S')"
echo "  ITViec:       $ITVIEC_COUNT jobs"
echo "  VietnamWorks: $VNW_COUNT jobs"
echo "  Merged:       $PROCESSED_COUNT unique jobs"
echo "============================================================"

# Alert if unusually low
TOTAL_RAW=$((ITVIEC_COUNT + VNW_COUNT))
if [ "$TOTAL_RAW" -lt 20 ]; then
    echo "⚠️  WARNING: Chỉ có $TOTAL_RAW raw jobs — cuối tuần hoặc crawler bị block!"
fi

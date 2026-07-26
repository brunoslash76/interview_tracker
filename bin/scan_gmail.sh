#!/bin/bash
# Interview Tracker — Gmail scan + persist + dashboard regen.
# Invoked by com.interview-tracker.scheduler.plist at 09:00 and 20:00 America/Sao_Paulo,
# by the menu bar app's "Refresh Now", or by hand.
# Paths are resolved relative to this script, so the project can live anywhere.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${INTERVIEW_TRACKER_DATA_DIR:-${HOME}/Library/Application Support/InterviewTracker}"
DB_FILE="${DATA_DIR}/interview_tracker.sqlite3"
LOG_FILE="${DATA_DIR}/logs/scan.log"
CONF="${INTERVIEW_TRACKER_CONFIG:-${DATA_DIR}/config.env}"

mkdir -p "${DATA_DIR}/logs"
PROGRESS_FILE="${DATA_DIR}/.scan_progress.json"
# shellcheck disable=SC1090
[ -f "${CONF}" ] && source "${CONF}"

emit_progress() {
  local phase="$1"
  local detail="${2:-}"
  /usr/bin/python3 -c "
import json, sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
phase = sys.argv[2]
payload = {'phase': phase, 'updated_at': datetime.now(timezone.utc).isoformat()}
if len(sys.argv) > 3 and sys.argv[3]:
    payload['detail'] = sys.argv[3]
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload), encoding='utf-8')
" "${PROGRESS_FILE}" "${phase}" "${detail}"
  echo "IT_PROGRESS:${phase}" >&2
}

LOCK_DIR="${DATA_DIR}/scan.lock"
if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] scan already running — exiting" >> "${DATA_DIR}/logs/scan.log"
  emit_progress "busy" "scan lock held"
  exit 2
fi

RAW_FILE=$(mktemp "${DATA_DIR}/raw_extraction.XXXXXX") || exit 1

cleanup() {
  rm -f "${RAW_FILE}"
  rmdir "${LOCK_DIR}" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

CLAUDE_BIN="${CLAUDE_BIN:-claude}"
if ! command -v "${CLAUDE_BIN}" >/dev/null 2>&1 && [ ! -x "${CLAUDE_BIN}" ]; then
  for c in "${HOME}/.local/bin/claude" /opt/homebrew/bin/claude /usr/local/bin/claude; do
    [ -x "$c" ] && CLAUDE_BIN="$c" && break
  done
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "${LOG_FILE}"; }
log "=== scan started (claude: ${CLAUDE_BIN}) ==="
emit_progress "starting"

if ! command -v "${CLAUDE_BIN}" >/dev/null 2>&1 && [ ! -x "${CLAUDE_BIN}" ]; then
  log "ERROR: claude CLI not found. Set CLAUDE_BIN in config.env (see: which claude)."
  emit_progress "failed" "claude CLI not found"
  exit 1
fi

# Scans under 30 minutes apart use the newest email timestamp actually read by
# the previous scan. Older scans retain the five-day overlap safety window.
if ! SCAN_WINDOW=$(/usr/bin/python3 "${ROOT}/bin/database.py" --db "${DB_FILE}" scan-window-json 2>>"${LOG_FILE}"); then
  log "ERROR: could not compute Gmail scan window"
  exit 1
fi
IFS=$'\t' read -r SEARCH_QUERY WINDOW_MODE EMAIL_WATERMARK < <(/usr/bin/python3 -c "
import json, sys
window = json.load(sys.stdin)
print(window['query'], window['mode'], window.get('latest_email_watermark') or '', sep='\t')
" <<< "${SCAN_WINDOW}")
log "searching Gmail with ${SEARCH_QUERY} (mode: ${WINDOW_MODE})"

if ! SCAN_CONFIG=$(/usr/bin/python3 "${ROOT}/bin/database.py" --db "${DB_FILE}" scan-config-json 2>>"${LOG_FILE}"); then
  log "ERROR: could not read scan configuration"
  exit 1
fi
IFS=$'\t' read -r EMAIL_FILTER GMAIL_INVOLVEMENT < <(/usr/bin/python3 -c "
import json, sys
config = json.load(sys.stdin)
print(config.get('email_filter', ''), config.get('gmail_involvement_filter', ''), sep='\t')
" <<< "${SCAN_CONFIG}")
if [[ -n "${EMAIL_FILTER}" ]]; then
  log "using email involvement filter for ${EMAIL_FILTER}"
fi
emit_progress "config"

JSON_SCHEMA='{
  "type": "object",
  "properties": {
    "interviews": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "thread_id": {"type": "string", "description": "Gmail thread ID"},
          "company": {"type": "string"},
          "position": {"type": "string"},
          "stage": {"type": "string", "enum": ["Initial Contact", "Phone Screen", "Technical Round", "Final Interview", "Offer"]},
          "status": {"type": "string", "description": "e.g. Active, Awaiting Response, Rejected, Withdrawn, Offer Received"},
          "interview_datetime": {"type": ["string", "null"], "description": "ISO 8601 if a specific date/time was mentioned, else null"},
          "contact_person": {"type": ["string", "null"]},
          "next_steps": {"type": ["string", "null"]},
          "meeting_link": {"type": ["string", "null"]},
          "last_email_date": {"type": ["string", "null"], "description": "ISO 8601 date of the most recent relevant email in the thread"},
          "notes": {"type": ["string", "null"]}
        },
        "required": ["thread_id", "company", "stage", "status"]
      }
    },
    "latest_email_date_seen": {
      "type": ["string", "null"],
      "description": "ISO 8601 timestamp of the newest Gmail message actually inspected during this scan, across all fetched threads"
    }
  },
  "required": ["interviews", "latest_email_date_seen"]
}'

PROMPT="You are scanning my Gmail for job-interview-related email threads: interview invitations, scheduling/confirmation emails, recruiter or HR replies about an application, technical/onsite interview logistics, and offer communications. Ignore generic job-board alerts, newsletters, and marketing.

Search using mcp__claude_ai_Gmail__search_threads with queries covering interview-related terms (e.g. interview, phone screen, technical interview, onsite, recruiter, hiring, offer, schedule a call, next steps). EVERY search query MUST include this exact boundary unchanged: ${SEARCH_QUERY}. Never issue a search without it and never replace it with an older or broader boundary. Run several searches with different terms since one query will not catch everything. Only call mcp__claude_ai_Gmail__get_thread for thread IDs returned by those bounded searches. For each candidate thread, read the full content before extracting data — do not guess from snippets alone."
if [[ "${WINDOW_MODE}" == "recent-watermark" ]]; then
  PROMPT="${PROMPT}

RECENT-SCAN GUARDRAIL: the previous successful scan was less than 30 minutes ago. The newest message it read was ${EMAIL_WATERMARK}. Process only messages newer than that watermark. Older messages included in a matching thread are context only; do not re-extract or reconsider them unless a newer message changes that application's current state."
fi
if [[ -n "${GMAIL_INVOLVEMENT}" ]]; then
  PROMPT="${PROMPT}

Every Gmail search query MUST also include this involvement filter for ${EMAIL_FILTER}: ${GMAIL_INVOLVEMENT}. Do not return threads that do not involve this address."
fi
PROMPT="${PROMPT}

For every distinct company/application you find, extract one record with:
- thread_id: the Gmail thread ID (if a company has multiple threads for the SAME application, pick the thread with the latest activity)
- company: company name
- position: job title/position
- stage: classify into exactly one of Initial Contact, Phone Screen, Technical Round, Final Interview, Offer — based on the FURTHEST stage reached in the thread, not the first email
- status: current application status in plain text (e.g. Active, Awaiting Response, Rejected, Withdrawn, Offer Received)
- interview_datetime: ISO 8601 date/time if a specific interview was scheduled and still relevant, else null
- contact_person: name (and email if available) of the recruiter/interviewer if mentioned, else null
- next_steps: brief plain-text description of what I concretely need to DO next, else null
- meeting_link: video call / scheduling link if present, else null
- last_email_date: ISO 8601 date of the most recent email in the thread
- notes: any other useful short context, else null

Also return latest_email_date_seen as the ISO 8601 timestamp of the newest individual Gmail message you actually inspected across every fetched thread. Return null only when no thread was fetched. This watermark must reflect message data, not the current clock time.

Output ONLY the structured JSON matching the provided schema — no prose, no markdown fences."

emit_progress "extracting"
if ! perl -e 'alarm shift; exec @ARGV' 600 "${CLAUDE_BIN}" -p "${PROMPT}" \
  --system-prompt "You are a headless data-extraction worker with no memory, no persona, and no context beyond this task. Use only the tools explicitly provided. Follow the instructions exactly and produce only the requested output." \
  --allowedTools "mcp__claude_ai_Gmail__search_threads mcp__claude_ai_Gmail__get_thread" \
  --disallowedTools "Bash Read Write Edit NotebookEdit WebFetch WebSearch Agent Task TaskCreate TaskUpdate TaskGet TaskList TaskOutput TaskStop Artifact ExitPlanMode" \
  --output-format json \
  --json-schema "${JSON_SCHEMA}" \
  --no-session-persistence 2>>"${LOG_FILE}" |
  /usr/bin/python3 -c "
import json, sys
outer = json.load(sys.stdin)
result = outer.get('result')
if isinstance(result, str):
    result = json.loads(result)
interviews = result.get('interviews', [])
if not isinstance(interviews, list):
    raise TypeError('interviews must be an array')
watermark = result.get('latest_email_date_seen')
if watermark is not None and not isinstance(watermark, str):
    raise TypeError('latest_email_date_seen must be a string or null')
json.dump({'interviews': interviews, 'latest_email_date_seen': watermark}, sys.stdout)
" > "${RAW_FILE}" 2>>"${LOG_FILE}"; then
  log "ERROR: claude invocation or JSON parsing failed"
  emit_progress "failed" "claude extraction failed"
  exit 1
fi

COUNT=$(/usr/bin/python3 -c "import json, sys; print(len(json.load(open(sys.argv[1]))['interviews']))" "${RAW_FILE}")
log "extracted ${COUNT} candidate records"

emit_progress "merging" "${COUNT}"
if ! /usr/bin/python3 "${ROOT}/bin/merge_interviews.py" "${RAW_FILE}" >> "${LOG_FILE}" 2>&1; then
  log "ERROR: failed to merge extracted records"
  emit_progress "failed" "merge failed"
  exit 1
fi

emit_progress "complete" "${COUNT}"
log "=== scan completed ==="

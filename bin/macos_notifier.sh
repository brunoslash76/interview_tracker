#!/bin/bash
# Interview Tracker — notifier.
# Invoked by com.interview-tracker.notifier.plist on WatchPaths events for
# the SQLite database. Idempotent: compares the data hash against the last
# notified hash and stays silent when nothing actually changed.
# Paths are resolved relative to this script.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${INTERVIEW_TRACKER_DATA_DIR:-${HOME}/Library/Application Support/InterviewTracker}"
DB_FILE="${DATA_DIR}/interview_tracker.sqlite3"
DASHBOARD_FILE="${DATA_DIR}/dashboard.html"
LAST_NOTIFIED_FILE="${DATA_DIR}/.last_notified_hash"
NTFY_TOPIC_FILE="${DATA_DIR}/.ntfy_topic"
CONF="${INTERVIEW_TRACKER_CONFIG:-${DATA_DIR}/config.env}"
LOG_FILE="${DATA_DIR}/logs/notifier.log"

mkdir -p "${DATA_DIR}/logs"
# shellcheck disable=SC1090
[ -f "${CONF}" ] && source "${CONF}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "${LOG_FILE}"; }
log "notifier fired (arg: ${1:-none})"

if ! SUMMARY_JSON=$(/usr/bin/python3 "${ROOT}/bin/database.py" --db "${DB_FILE}" summary-json 2>>"${LOG_FILE}"); then
  log "ERROR: could not read latest scan summary"
  exit 1
fi
if [[ "${SUMMARY_JSON}" == "null" ]]; then
  log "no successful scan summary yet — nothing to notify"
  exit 0
fi

if ! SUMMARY_VALUES=$(printf '%s' "${SUMMARY_JSON}" | /usr/bin/python3 -c "
import json, sys
s = json.load(sys.stdin)
print(s['data_hash'])
print(s['total'])
print(s['upcoming'])
print(s['offers'])
print(', '.join(s.get('new_company_names', [])))
" 2>>"${LOG_FILE}"); then
  log "ERROR: latest scan summary is invalid"
  exit 1
fi
{
  IFS= read -r CURRENT_HASH
  IFS= read -r TOTAL
  IFS= read -r UPCOMING
  IFS= read -r OFFERS
  IFS= read -r NEW_NAMES
} <<< "${SUMMARY_VALUES}"
[[ -z "${CURRENT_HASH}" ]] && { log "ERROR: could not read data_hash"; exit 1; }

LAST_HASH=""
[[ -f "${LAST_NOTIFIED_FILE}" ]] && LAST_HASH=$(cat "${LAST_NOTIFIED_FILE}")

if [[ "${CURRENT_HASH}" == "${LAST_HASH}" ]]; then
  log "data unchanged since last notification (hash ${CURRENT_HASH:0:12}...) — staying silent"
  exit 0
fi

if [[ -n "${NEW_NAMES}" ]]; then
  BODY="Total ${TOTAL} · Upcoming ${UPCOMING} · Offers ${OFFERS}. New: ${NEW_NAMES}."
else
  BODY="Total ${TOTAL} · Upcoming ${UPCOMING} · Offers ${OFFERS}. Existing records updated."
fi
log "changes detected — notifying. ${BODY}"

HTTP_PORT_FILE="${DATA_DIR}/.http_port"
if [[ -f "${HTTP_PORT_FILE}" ]]; then
  OPEN_URL="http://127.0.0.1:$(cat "${HTTP_PORT_FILE}")/dashboard"
else
  OPEN_URL="file://${DASHBOARD_FILE}"
fi

# --- Mac notification: prefer terminal-notifier, fall back to osascript ------
if command -v terminal-notifier >/dev/null 2>&1; then
  TN="$(command -v terminal-notifier)"
elif [ -x /opt/homebrew/bin/terminal-notifier ]; then
  TN=/opt/homebrew/bin/terminal-notifier
else
  TN=""
fi
if [[ -n "${TN}" ]]; then
  "${TN}" -title "Interview Tracker updated" -message "${BODY}" \
    -open "${OPEN_URL}" -sound default >> "${LOG_FILE}" 2>&1 \
    && log "sent via terminal-notifier" || log "terminal-notifier failed"
else
  osascript -e "display notification \"${BODY//\"/\\\"}\" with title \"Interview Tracker updated\"" 2>>"${LOG_FILE}" \
    && log "sent via osascript" || log "osascript failed (brew install terminal-notifier for reliable alerts)"
fi

# --- Phone + Watch push via ntfy (config.env NTFY_TOPIC or .ntfy_topic) ------
TOPIC="${NTFY_TOPIC:-}"
[[ -z "${TOPIC}" && -f "${NTFY_TOPIC_FILE}" ]] && TOPIC=$(cat "${NTFY_TOPIC_FILE}")
if [[ -n "${TOPIC}" ]]; then
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -d "${BODY}" -H "Title: Interview Tracker updated" -H "Tags: briefcase" \
    -H "Click: ${OPEN_URL}" "https://ntfy.sh/${TOPIC}")
  log "ntfy push sent, HTTP ${HTTP_CODE}"
else
  log "no ntfy topic set — Mac only, no phone/watch push"
fi

echo "${CURRENT_HASH}" > "${LAST_NOTIFIED_FILE}"
log "done"

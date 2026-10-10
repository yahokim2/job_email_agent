#!/bin/bash
DIR="/Users/younghokim/LLM_Spaces/job_email_agent"
STAMP="$DIR/logs/.last_run"
TODAY=$(date +%Y-%m-%d)

# 오늘 이미 성공했으면 종료
[ "$(cat "$STAMP" 2>/dev/null)" = "$TODAY" ] && exit 0

# 06:00 이전 부팅이면 건너뜀 (06:00 정시 실행에 맡김)
[ "$(date +%H)" -lt 6 ] && exit 0

# 부팅 직후 네트워크 대기 (최대 5분)
for i in {1..30}; do
  nc -z imap.gmail.com 993 2>/dev/null && break
  sleep 10
done

/bin/bash "$DIR/scripts/run_ingest.sh" && echo "$TODAY" > "$STAMP"

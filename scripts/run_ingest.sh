#!/bin/bash
# launchd가 매일 호출하는 수집 스크립트.
#   1) Docker 엔진이 꺼져 있으면 Docker Desktop을 켜고 준비될 때까지 기다린다 (최대 5분)
#   2) backend 컨테이너를 한 번 실행한다 (네트워크가 아직 안 붙었을 수 있어 최대 3회 시도)
# 결과는 logs/ingest.log 에 시각과 함께 남는다.

# launchd는 PATH가 최소한이라 docker 위치를 직접 추가
export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/ingest.log"
mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR" || exit 1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }

log "===== 수집 시작 ====="

# 1) Docker 엔진 준비
if ! docker info >/dev/null 2>&1; then
  log "Docker 엔진이 꺼져 있어 Docker Desktop을 실행합니다."
  open -a Docker
  for _ in $(seq 1 60); do
    sleep 5
    docker info >/dev/null 2>&1 && break
  done
fi
if ! docker info >/dev/null 2>&1; then
  log "실패: Docker 엔진이 5분 안에 준비되지 않았습니다."
  exit 1
fi

# 2) 수집 실행 (-T: 터미널이 없는 환경이라 TTY 할당 끔)
for attempt in 1 2 3; do
  log "backend 실행 (시도 $attempt/3)"
  docker compose run --rm -T backend >> "$LOG_FILE" 2>&1
  code=$?
  if [ "$code" -eq 0 ]; then
    log "성공"
    exit 0
  fi
  log "실패 (종료 코드 $code)"
  [ "$attempt" -lt 3 ] && sleep 60
done

log "최종 실패: 3회 모두 실패했습니다."
exit 1

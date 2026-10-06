#!/bin/bash
# launchd 등록/해제 스크립트 (macOS)
#   bash scripts/install_launchd.sh              매일 06:00 에 등록
#   bash scripts/install_launchd.sh 7 30         매일 07:30 으로 등록 (시 분)
#   bash scripts/install_launchd.sh --uninstall  등록 해제
set -e

LABEL="com.jobagent.ingest"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"

if [ "$1" = "--uninstall" ]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "해제 완료: $LABEL"
  exit 0
fi

if ! [[ "${1:-6}" =~ ^[0-9]{1,2}$ && "${2:-0}" =~ ^[0-9]{1,2}$ ]]; then
  echo "사용법: bash scripts/install_launchd.sh [시 [분]]   예) 6 0"
  exit 1
fi
HOUR=$((10#${1:-6}))
MINUTE=$((10#${2:-0}))
if [ "$HOUR" -gt 23 ] || [ "$MINUTE" -gt 59 ]; then
  echo "시는 0~23, 분은 0~59 범위여야 합니다."
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/logs"

cat > "$PLIST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$PROJECT_DIR/scripts/run_ingest.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>$HOUR</integer>
    <key>Minute</key>
    <integer>$MINUTE</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$PROJECT_DIR/logs/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_DIR/logs/launchd.err.log</string>
</dict>
</plist>
PLIST_EOF

# 이미 등록돼 있으면 먼저 내리고 다시 등록 (시각을 바꿀 때도 같은 명령)
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"

printf "등록 완료: 매일 %02d:%02d 에 수집을 실행합니다.\n" "$HOUR" "$MINUTE"
echo "  로그      : $PROJECT_DIR/logs/ingest.log"
echo "  지금 실행 : launchctl kickstart -k $DOMAIN/$LABEL"
echo "  상태 확인 : launchctl print $DOMAIN/$LABEL | head -20"
echo "  해제      : bash scripts/install_launchd.sh --uninstall"

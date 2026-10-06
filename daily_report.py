"""
최근 N일 이내 들어온, 아직 모집 중인 공고만 추려서 핵심 요약 + 상세 리포트를 생성.

ingest.py가 "수집", search.py가 "검색"을 담당한다면, 이 파일은 "브리핑"을 담당한다.

실행: python daily_report.py
"""

import os
from datetime import datetime

from dotenv import load_dotenv
import psycopg2
import anthropic

load_dotenv()

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ.get("DB_NAME", "job_agent"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
}
REPORT_LOOKBACK_DAYS = int(os.environ.get("REPORT_LOOKBACK_DAYS", "3"))
MY_SKILLS = os.environ.get("MY_SKILLS", "")

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

REPORT_PROMPT = """다음은 최근 <<DAYS>>일 이내 새로 들어온, 아직 모집 중인 구인 프로젝트 목록입니다.
<<SKILLS_LINE>>

아래 형식으로 한국어 리포트를 작성하세요. 마크다운으로 작성하고, 다른 설명은 붙이지 마세요.
목록에 있는 항목의 링크는 절대 출력하지 마세요 (별도로 자동 첨부됩니다) — 이 지침이 응답 길이를 줄여 모든 항목을 다 다루는 데 중요합니다.

## 오늘의 핵심 요약
전체 건수, 눈에 띄는 항목(최고 단가, 마감 임박, 보유 스킬과 잘 맞는 것)을 3~5줄로 요약하세요.

## 상세 리포트
목록에 있는 항목 번호를 그대로 유지해서, 각 공고를 번호 매겨 2~3문장으로 요약하세요.
보유 스킬과 맞는 이유가 있으면 짧게 언급하세요. 목록의 모든 항목을 빠짐없이 다루세요.

목록:
<<POSTINGS_TEXT>>
"""


def fetch_recent_open_postings(conn, days: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT title, company, source, required_skills, duties, location,
                   expected_pay, start_date, expected_duration, deadline, detail_url, received_at
            FROM job_postings
            WHERE (is_closed IS NOT TRUE)
              AND deleted_at IS NULL
              AND received_at >= NOW() - (%s || ' days')::interval
            ORDER BY received_at DESC
            """,
            (days,),
        )
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, r)) for r in cur.fetchall()]


def format_postings_for_prompt(rows) -> str:
    lines = []
    for i, r in enumerate(rows, start=1):
        lines.append(
            f"{i}. [{r['source']}] {r['title']}\n"
            f"   회사: {r['company'] or '비공개'} / 스킬: {', '.join(r['required_skills'] or [])}\n"
            f"   예상금액: {r['expected_pay'] or '정보없음'} / 근무위치: {r['location'] or '정보없음'}\n"
            f"   시작일: {r['start_date'] or '정보없음'} / 기간: {r['expected_duration'] or '정보없음'}"
        )
    return "\n\n".join(lines)


def generate_report(rows, days: int) -> str:
    postings_text = format_postings_for_prompt(rows)
    skills_line = f"내 보유 스킬: {MY_SKILLS}" if MY_SKILLS else "보유 스킬 정보 없음 (일반적인 기준으로 요약)"

    prompt = (
        REPORT_PROMPT.replace("<<DAYS>>", str(days))
        .replace("<<SKILLS_LINE>>", skills_line)
        .replace("<<POSTINGS_TEXT>>", postings_text)
    )
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    report_body = response.content[0].text

    # 링크는 LLM이 안 베끼게 하고, 여기서 직접 정확한 URL로 붙임 (복사 실수·토큰 낭비 방지)
    link_lines = [
        f"{i}. {r['title']} — {r['detail_url']}"
        for i, r in enumerate(rows, start=1)
        if r["detail_url"]
    ]
    if link_lines:
        report_body += "\n\n## 링크\n" + "\n".join(link_lines)

    return report_body


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    rows = fetch_recent_open_postings(conn, REPORT_LOOKBACK_DAYS)
    conn.close()

    if not rows:
        print(f"최근 {REPORT_LOOKBACK_DAYS}일 이내 모집 중인 공고가 없습니다.")
        return

    print(f"최근 {REPORT_LOOKBACK_DAYS}일 이내 모집 중 공고 {len(rows)}건 발견, 리포트 생성 중...\n")
    report_text = generate_report(rows, REPORT_LOOKBACK_DAYS)
    print(report_text)

    os.makedirs("reports", exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d_%H%M")
    path = f"reports/{today}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\n(리포트 파일 저장됨: {path})")


if __name__ == "__main__":
    main()

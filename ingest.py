"""
구인 추천 메일 수집·파싱·저장 파이프라인 (2단계: 멀티 프로젝트 + 상세페이지)

흐름:
  1. Gmail IMAP 접속 → 등록된 구인사이트에서 온 안 읽은 메일 검색
  2. 제목에 "(광고)"와 수신자 이름이 둘 다 있는 메일만 대상으로 선별
     (그 외 뉴스레터성 메일은 스킵하고 읽음 처리만 함)
  3. 메일 본문에서 여러 개의 프로젝트를 배열로 추출 (LLM)
  4. 각 프로젝트의 "더 알아보기" 링크를 찾아 상세페이지 방문
  5. 상세페이지에서 예상금액/시작예정일/예상기간/근무위치/모집종료여부 추출 (LLM)
  6. 프로젝트 단위로 PostgreSQL에 저장 (원문+추출결과 모두 보존 → 근거 추적용)
  7. 처리한 메일은 읽음 처리 (재처리 방지)

실행: python ingest.py
"""

import os
import re
import json
import time
import email
from email.header import decode_header
from datetime import datetime, date, timedelta

from dotenv import load_dotenv
from imapclient import IMAPClient
from bs4 import BeautifulSoup
import psycopg2
from psycopg2.extras import Json
from pgvector.psycopg2 import register_vector
import anthropic
import requests
import voyageai

load_dotenv()

GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
# 콤마로 여러 구인사이트 발신 도메인을 나열 가능 (예: "wantedlab.com,jobkorea.co.kr")
SENDER_FILTERS = [s.strip() for s in os.environ.get("SENDER_FILTER", "wantedlab.com").split(",") if s.strip()]
# 제목에 이 이름이 들어있는 메일만 "개인 맞춤 추천" 메일로 간주 (여러 프로젝트가 나열된 형태)
RECIPIENT_NAME = os.environ.get("RECIPIENT_NAME", "김영호")
# 안전장치: 실수로 오래된 메일이 대량 안읽음 처리돼도 최근 N일 이내 것만 처리
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "14"))

# 발신 도메인 → 구인사이트 이름 매핑 (새 사이트 추가 시 여기에도 추가)
DOMAIN_TO_SITE = {
    "wantedlab.com": "원티드긱스",   # 실제 뉴스레터 발신 도메인/브랜드명
    "jobkorea.co.kr": "잡코리아",
    "saramin.co.kr": "사람인",
}

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ.get("DB_NAME", "job_agent"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
}

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
EMBEDDING_DIM = 512  # migration_003_pgvector.sql의 vector(512)와 반드시 일치해야 함

# ---------------------------------------------------------------------------
# 메일 본문 → 여러 프로젝트 배열 추출용 프롬프트
# ---------------------------------------------------------------------------
EXTRACTION_PROMPT = """다음은 프리랜서 프로젝트 추천 메일 본문입니다. 이 메일에는 여러 개의 프로젝트가
"추천 프로젝트 1", "추천 프로젝트 2"... 식으로 나열되어 있습니다.
아래 JSON 스키마에 맞춰 이메일에 있는 **모든** 프로젝트를 등장 순서 그대로 배열로 추출하세요.
정보가 없으면 null을 넣으세요. JSON 외의 다른 텍스트는 출력하지 마세요.

스키마:
{
  "site": "구인사이트명. 메일 본문/서명/로고 등에서 판단 (string or null)",
  "projects": [
    {
      "title": "프로젝트 명 (string or null)",
      "required_skills": ["스킬1", "스킬2"],
      "duties": "주요 담당 업무를 한두 문장으로 요약 (string or null)",
      "summary": "이 프로젝트 한 줄 요약 (string)"
    }
  ]
}

메일 본문:
---
<<EMAIL_TEXT>>
---
"""

# ---------------------------------------------------------------------------
# 프로젝트 상세페이지 → 세부 필드 추출용 프롬프트
# ---------------------------------------------------------------------------
DETAIL_EXTRACTION_PROMPT = """다음은 프리랜서 프로젝트 상세페이지에서 추출한 텍스트입니다.
아래 JSON 스키마에 맞춰 정보를 추출하세요. 정보가 없으면 null을 넣으세요.
페이지 안에 "모집이 종료되었습니다"와 같이 모집 마감을 알리는 문구가 있으면 is_closed를 true로,
아니면 false로 하세요. JSON 외의 다른 텍스트는 출력하지 마세요.

스키마:
{
  "expected_pay": "예상 금액/단가 (string or null)",
  "start_date": "시작 예정일 (string or null)",
  "expected_duration": "예상 진행 기간 (string or null)",
  "work_location": "근무 위치 (string or null)",
  "is_closed": true 또는 false
}

상세페이지 텍스트:
---
<<DETAIL_TEXT>>
---
"""


def connect_imap() -> IMAPClient:
    client = IMAPClient("imap.gmail.com", ssl=True)
    client.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    client.select_folder("INBOX")
    return client


def fetch_unread_job_emails(client: IMAPClient, sender_filters: list):
    """안 읽은 메일 중 등록된 구인사이트 발신자 중 하나와 일치하고,
    최근 LOOKBACK_DAYS일 이내에 온 메일의 UID 목록만 반환.
    (실수로 오래된 메일이 대량 '안읽음' 처리돼도 예전 것까지 싹 다 처리되는 사고 방지)"""
    since_date = date.today() - timedelta(days=LOOKBACK_DAYS)
    all_uids = set()
    for sender in sender_filters:
        uids = client.search(["UNSEEN", "FROM", sender, "SINCE", since_date])
        all_uids.update(uids)
    return sorted(all_uids)


def guess_site_from_sender(from_header: str) -> str:
    """LLM이 사이트를 못 알아냈을 때 발신자 도메인으로 보완 추정"""
    addr = email.utils.parseaddr(from_header)[1]
    domain = addr.split("@")[-1].lower() if "@" in addr else ""
    for key, name in DOMAIN_TO_SITE.items():
        if key in domain:
            return name
    return "기타"


def decode_mime_header(raw_header: str) -> str:
    parts = decode_header(raw_header)
    decoded = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            decoded += text.decode(enc or "utf-8", errors="ignore")
        else:
            decoded += text
    return decoded


def is_target_subject(subject: str, site: str) -> bool:
    """제목 필터링 규칙. 사이트마다 메일 형식이 다르므로 사이트별로 분기한다.
    (지금은 원티드긱스 규칙만 구현됨 — 잡코리아 등 추가 시 여기에 elif로 규칙 추가)"""
    if site == "원티드긱스":
        # "(광고) 000님을 위한 추천 프로젝트" 처럼 여러 프로젝트가 나열된 메일만 대상
        return "(광고)" in subject and RECIPIENT_NAME in subject
    # 사이트별 규칙이 아직 없으면 일단 전부 대상으로 처리 (기존 단일 공고 추출 방식)
    return True


def extract_text_from_email(msg: email.message.Message):
    """멀티파트 이메일에서 (순수 텍스트, HTML 원본) 튜플을 반환.
    HTML 원본은 '더 알아보기' 링크의 실제 URL을 뽑아내기 위해 별도로 보존한다."""
    html_body = None
    text_body = None

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/html" and html_body is None:
                html_body = part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="ignore"
                )
            elif ctype == "text/plain" and text_body is None:
                text_body = part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="ignore"
                )
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            text_body = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")

    if html_body:
        soup = BeautifulSoup(html_body, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        return text, html_body
    return (text_body or ""), ""


def extract_more_info_links(html_body: str, site: str) -> list:
    """'더 알아보기' 버튼들의 실제 링크(href)를 등장 순서대로 반환.
    프로젝트 배열과 같은 순서로 나온다고 가정하고 인덱스로 매칭한다.
    (지금은 원티드긱스의 '더 알아보기'/'자세히' 버튼 텍스트 기준 — 사이트마다 버튼 문구나
     HTML 구조가 다를 수 있으므로, 다른 사이트 추가 시 site 값으로 분기해서 확장)"""
    if "원티드" not in (site or "") or not html_body:
        print(f"    [진단] 링크 탐색 건너뜀 — site='{site}', html_body 길이={len(html_body or '')}")
        return []
    soup = BeautifulSoup(html_body, "html.parser")
    links = []
    for a in soup.find_all("a"):
        text = a.get_text(strip=True).replace("\xa0", " ")
        if "더 알아보기" in text or "자세히" in text or "더알아보기" in text:
            href = a.get("href")
            if href:
                links.append(href)
    if not links:
        total_a = len(soup.find_all("a"))
        print(f"    [진단] <a> 태그 {total_a}개 중 '더 알아보기' 텍스트 매칭 0건 "
              f"(버튼이 이미지일 수 있음 — 필요시 코드 조정 필요)")
    return links


def extract_projects_llm(email_text: str) -> dict:
    """Claude API로 메일 하나에 들어있는 여러 프로젝트를 배열로 추출"""
    truncated = email_text[:8000]
    prompt = EXTRACTION_PROMPT.replace("<<EMAIL_TEXT>>", truncated)

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"site": None, "projects": []}


def build_embedding_text(project: dict, detail: dict) -> str:
    """검색에 쓰일 임베딩 원문 구성 — 제목/업무/스킬/근무위치를 하나의 텍스트로 합침"""
    parts = [
        project.get("title") or "",
        project.get("duties") or "",
        ", ".join(project.get("required_skills") or []),
        detail.get("work_location") or "",
        project.get("summary") or "",
    ]
    return " | ".join(p for p in parts if p)


def generate_embeddings_batch(texts: list):
    """텍스트 여러 개를 한 번의 API 호출로 임베딩. 실패하면 None 리스트 반환
    (한 메일의 프로젝트 전체를 한 번에 보내 API 호출 횟수를 최소화 — RPM 제한 회피)"""
    if not texts:
        return []
    try:
        result = voyage.embed(
            texts, model="voyage-4-lite", input_type="document", output_dimension=EMBEDDING_DIM
        )
        return result.embeddings
    except Exception as e:
        print(f"    배치 임베딩 생성 실패: {e}")
        return [None] * len(texts)


def fetch_project_detail_text(url: str) -> str:
    """프로젝트 상세페이지를 방문해 텍스트만 추출. 로그인 필요 페이지면 빈 내용이 올 수 있음."""
    try:
        resp = requests.get(
            url, timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    상세페이지 접속 실패: {e}")
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.get_text(separator="\n", strip=True)


def extract_detail_fields_llm(detail_text: str) -> dict:
    """상세페이지 텍스트에서 예상금액/시작일/기간/근무위치/모집종료여부 추출"""
    if not detail_text:
        return {}
    truncated = detail_text[:6000]
    prompt = DETAIL_EXTRACTION_PROMPT.replace("<<DETAIL_TEXT>>", truncated)
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"      [진단] 상세정보 JSON 파싱 실패, LLM 원본 응답: {raw[:300]!r}")
        return {}


def save_project_to_db(conn, message_id: str, project_index: int, received_at: datetime,
                         raw_text: str, project: dict, detail: dict, detail_url: str, source: str,
                         embedding=None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO job_postings
                (email_message_id, project_index, source, title, required_skills,
                 duties, location, expected_pay, start_date, expected_duration,
                 detail_url, is_closed, summary, raw_text, parsed_json, received_at, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (email_message_id, project_index) DO NOTHING
            """,
            (
                message_id,
                project_index,
                source,
                project.get("title"),
                project.get("required_skills") or [],
                project.get("duties"),
                detail.get("work_location"),
                detail.get("expected_pay"),
                detail.get("start_date"),
                detail.get("expected_duration"),
                detail_url,
                detail.get("is_closed"),
                project.get("summary"),
                raw_text,
                Json({"project": project, "detail": detail}),
                received_at,
                embedding,
            ),
        )
    conn.commit()


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    register_vector(conn)  # 파이썬 리스트를 pgvector의 vector 타입으로 자동 변환
    client = connect_imap()

    try:
        uids = fetch_unread_job_emails(client, SENDER_FILTERS)
        print(f"처리 대상 메일 {len(uids)}건")

        if not uids:
            return

        messages = client.fetch(uids, ["BODY.PEEK[]", "INTERNALDATE"])

        for uid, data in messages.items():
            raw_email = data[b"BODY[]"]
            received_at = data.get(b"INTERNALDATE", datetime.now())
            msg = email.message_from_bytes(raw_email)

            message_id = msg.get("Message-ID", f"no-id-{uid}")
            subject = decode_mime_header(msg.get("Subject", ""))
            # 발신 도메인으로 사이트를 먼저 추정 (LLM 추출 전에 필터링 규칙을 정하기 위함)
            site_guess = guess_site_from_sender(msg.get("From", ""))

            # 사이트별 제목 필터링 규칙 적용 (지금은 원티드긱스만 "(광고)+이름" 규칙 적용)
            if not is_target_subject(subject, site_guess):
                print(f"- 건너뜀(대상 아님): {subject[:50]}")
                client.add_flags(uid, [b"\\Seen"])
                continue

            print(f"- 파싱 중: {subject[:50]}")
            text, html_body = extract_text_from_email(msg)

            parsed = extract_projects_llm(text)
            # 사이트명은 LLM 추출값 대신 발신 도메인 기반의 확정값을 신뢰
            # (LLM이 "wanted gigs"처럼 언어/표현을 매번 다르게 뽑아 필터링이 불안정해지는 것 방지)
            site = site_guess
            projects = parsed.get("projects") or []
            links = extract_more_info_links(html_body, site)

            print(f"  · 프로젝트 {len(projects)}건 발견, 링크 {len(links)}건 발견")

            # 1단계: 프로젝트별 상세정보 수집 (링크·LLM 호출)
            collected = []  # (idx, project, detail, detail_url) 목록
            for idx, project in enumerate(projects, start=1):
                detail_url = links[idx - 1] if idx - 1 < len(links) else None
                detail = {}
                if detail_url:
                    print(f"    - 프로젝트 {idx}/{len(projects)} 상세페이지 확인 중...")
                    detail_text = fetch_project_detail_text(detail_url)
                    detail = extract_detail_fields_llm(detail_text)
                    time.sleep(1)  # 상세페이지·API 연속 호출 과부하 방지
                collected.append((idx, project, detail, detail_url))

            # 2단계: 이 메일의 프로젝트 전체를 한 번의 API 호출로 임베딩 (RPM 제한 회피)
            embedding_texts = [build_embedding_text(p, d) for _, p, d, _ in collected]
            embeddings = generate_embeddings_batch(embedding_texts)

            # 3단계: DB 저장
            for (idx, project, detail, detail_url), embedding in zip(collected, embeddings):
                save_project_to_db(conn, message_id, idx, received_at, text, project, detail,
                                    detail_url, site, embedding)

            # 처리 완료 → 읽음 처리 (재처리 방지)
            client.add_flags(uid, [b"\\Seen"])

            # 메일이 여러 건일 때 다음 메일로 넘어가기 전 RPM 제한 회피용 여유
            time.sleep(2)

        print("완료")
    finally:
        # 중간에 에러가 나도 반드시 세션을 정리 → "동시 접속 초과" 재발 방지
        try:
            client.logout()
        except Exception:
            pass
        conn.close()


if __name__ == "__main__":
    main()

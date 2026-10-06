"""
저장된 구인 프로젝트 중에서, 입력한 조건과 의미적으로 유사한 것을 찾아주는 검색 스크립트.

ingest.py가 "메일 → DB 채워넣기"를 담당한다면, 이 파일은 "DB에서 찾아보기"를 담당한다.
(나중에 5단계 QA 대시보드가 이 검색 로직을 그대로 가져다 쓸 예정)

실행: python search.py "여의도 Java 백엔드"
      또는 인자 없이 실행하면 프롬프트로 입력받음
"""

import os
import sys

from dotenv import load_dotenv
import psycopg2
from pgvector.psycopg2 import register_vector
import voyageai

load_dotenv()

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ.get("DB_NAME", "job_agent"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
}
EMBEDDING_DIM = 512  # ingest.py, migration_003_pgvector.sql과 반드시 일치해야 함

voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])


def embed_query(text: str):
    """검색어를 벡터로 변환. input_type='query'로 문서용 임베딩과 구분해 검색 정확도를 높임"""
    result = voyage.embed([text], model="voyage-4-lite", input_type="query", output_dimension=EMBEDDING_DIM)
    return result.embeddings[0]


def search(conn, query_text: str, top_k: int = 5):
    query_vector = embed_query(query_text)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT title, company, expected_pay, start_date, expected_duration,
                   location, is_closed, detail_url,
                   embedding <=> %s::vector AS distance
            FROM job_postings
            WHERE embedding IS NOT NULL AND deleted_at IS NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (query_vector, query_vector, top_k),
        )
        return cur.fetchall()


def main():
    query_text = " ".join(sys.argv[1:]).strip()
    if not query_text:
        query_text = input("검색어를 입력하세요 (예: 여의도 Java 백엔드): ").strip()
    if not query_text:
        print("검색어가 비어있습니다.")
        return

    conn = psycopg2.connect(**DB_CONFIG)
    register_vector(conn)

    try:
        rows = search(conn, query_text)
        if not rows:
            print("저장된 임베딩이 없거나 검색 결과가 없습니다. (ingest.py를 먼저 돌려서 데이터를 쌓아주세요)")
            return

        print(f"\n'{query_text}' 검색 결과 (유사도 높은 순):\n")
        for i, row in enumerate(rows, start=1):
            title, company, pay, start_date, duration, location, is_closed, url, distance = row
            status = "모집종료" if is_closed else "모집중"
            similarity = 1 - distance  # 코사인 거리를 유사도(0~1)로 환산, 참고용
            print(f"{i}. [{status}] {title}")
            if company:
                print(f"   회사: {company}")
            print(f"   예상금액: {pay or '정보없음'} / 시작일: {start_date or '정보없음'} / 기간: {duration or '정보없음'}")
            print(f"   근무위치: {location or '정보없음'}")
            print(f"   유사도: {similarity:.3f}")
            if url:
                print(f"   링크: {url}")
            print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()

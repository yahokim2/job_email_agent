"""
이미 DB에 쌓여있지만 임베딩이 없는 기존 프로젝트들에 임베딩을 채워넣는 일회성 스크립트.
(3단계 도입 전에 저장된 데이터, 또는 임베딩 생성이 중간에 실패했던 행들 대상)

여러 건을 하나의 API 호출로 묶어서(배치) 처리 — Voyage 무료/미인증 계정의
분당 요청 수(RPM) 제한에 걸리지 않도록 호출 횟수 자체를 줄인다.

실행: python backfill_embeddings.py
"""

import os
import time

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
BATCH_SIZE = 20       # 한 번의 API 호출에 묶어서 보낼 개수
BATCH_INTERVAL_SEC = 22  # 분당 3건(RPM) 제한에 안전하게 맞추기 위한 배치 간 대기시간

voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])


def build_embedding_text(row: dict) -> str:
    parts = [
        row.get("title") or "",
        row.get("duties") or "",
        ", ".join(row.get("required_skills") or []),
        row.get("location") or "",
        row.get("summary") or "",
    ]
    return " | ".join(p for p in parts if p)


def generate_embeddings_batch(texts: list):
    """텍스트 여러 개를 한 번의 API 호출로 임베딩. 실패하면 None 리스트 반환"""
    try:
        result = voyage.embed(
            texts, model="voyage-4-lite", input_type="document", output_dimension=EMBEDDING_DIM
        )
        return result.embeddings
    except Exception as e:
        print(f"  배치 임베딩 생성 실패: {e}")
        return [None] * len(texts)


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    register_vector(conn)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, duties, required_skills, location, summary "
            "FROM job_postings WHERE embedding IS NULL"
        )
        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, r)) for r in cur.fetchall()]

    print(f"임베딩 없는 행 {len(rows)}건 발견")

    # 임베딩할 텍스트가 아예 없는 행은 미리 걸러냄 (API 호출 낭비 방지)
    valid_rows = []
    for row in rows:
        text = build_embedding_text(row)
        if text.strip():
            row["_embedding_text"] = text
            valid_rows.append(row)
        else:
            print(f"  id={row['id']} 스킵 (임베딩할 텍스트 없음)")

    for batch_start in range(0, len(valid_rows), BATCH_SIZE):
        batch = valid_rows[batch_start:batch_start + BATCH_SIZE]
        texts = [r["_embedding_text"] for r in batch]

        print(f"배치 {batch_start // BATCH_SIZE + 1} 처리 중 ({len(batch)}건)...")
        embeddings = generate_embeddings_batch(texts)

        for row, embedding in zip(batch, embeddings):
            if embedding is None:
                print(f"  id={row['id']} 스킵 (임베딩 생성 실패)")
                continue
            with conn.cursor() as cur:
                cur.execute("UPDATE job_postings SET embedding = %s WHERE id = %s", (embedding, row["id"]))
            conn.commit()
            print(f"  id={row['id']} 완료: {row['title']}")

        # 다음 배치가 남아있으면 RPM 제한 회피를 위해 대기
        if batch_start + BATCH_SIZE < len(valid_rows):
            print(f"  (다음 배치까지 {BATCH_INTERVAL_SEC}초 대기 — 무료/미인증 계정 RPM 제한 회피)")
            time.sleep(BATCH_INTERVAL_SEC)

    conn.close()
    print("백필 완료")


if __name__ == "__main__":
    main()

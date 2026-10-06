-- PostgreSQL 컨테이너가 "처음 만들어질 때" 한 번만 자동 실행된다.
-- (migration_002~005를 합친 최종 스키마. 이후 컬럼을 추가하면 이 파일도 같이 갱신할 것)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS job_postings (
    id                SERIAL PRIMARY KEY,
    email_message_id  TEXT NOT NULL,
    project_index     INTEGER NOT NULL DEFAULT 1,
    source            TEXT NOT NULL DEFAULT '원티드긱스',
    company           TEXT,
    title             TEXT,
    required_skills   TEXT[],
    duties            TEXT,
    salary_range      TEXT,
    location          TEXT,
    expected_pay      TEXT,
    start_date        TEXT,
    expected_duration TEXT,
    deadline          DATE,
    job_url           TEXT,
    detail_url        TEXT,
    is_closed         BOOLEAN,
    summary           TEXT,
    raw_text          TEXT,
    parsed_json       JSONB,
    received_at       TIMESTAMP,
    created_at        TIMESTAMP NOT NULL DEFAULT now(),
    embedding         vector(512),
    status            TEXT NOT NULL DEFAULT 'new',   -- new | interested | hold | rejected
    status_updated_at TIMESTAMP,
    deleted_at        TIMESTAMP,                      -- 값이 있으면 대시보드에서 삭제된 공고

    UNIQUE (email_message_id, project_index)
);

CREATE INDEX IF NOT EXISTS idx_job_postings_received_at ON job_postings (received_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_postings_deadline ON job_postings (deadline);
CREATE INDEX IF NOT EXISTS idx_job_postings_is_closed ON job_postings (is_closed);
CREATE INDEX IF NOT EXISTS idx_job_postings_status ON job_postings (status);
CREATE INDEX IF NOT EXISTS idx_job_postings_deleted_at ON job_postings (deleted_at);
CREATE INDEX IF NOT EXISTS idx_job_postings_embedding
    ON job_postings USING hnsw (embedding vector_cosine_ops);

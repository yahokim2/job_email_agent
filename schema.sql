-- 구인 추천 메일 저장용 스키마 (메일 하나당 여러 프로젝트가 들어갈 수 있는 구조)
-- 실행: psql -d job_agent -f schema.sql

CREATE TABLE IF NOT EXISTS job_postings (
    id                SERIAL PRIMARY KEY,
    email_message_id  TEXT NOT NULL,          -- 메일 Message-ID
    project_index     INTEGER NOT NULL DEFAULT 1,  -- 한 메일 안에서 몇 번째 프로젝트인지
    source            TEXT NOT NULL DEFAULT '원티드긱스',
    company           TEXT,
    title             TEXT,
    required_skills   TEXT[],
    duties            TEXT,                   -- 주요 담당 업무 (메일 본문에서)
    salary_range      TEXT,
    location           TEXT,                   -- 근무 위치 (상세페이지에서 보완)
    expected_pay      TEXT,                   -- 예상 금액/단가 (상세페이지)
    start_date        TEXT,                   -- 시작 예정일 (상세페이지)
    expected_duration TEXT,                   -- 예상 진행 기간 (상세페이지)
    deadline          DATE,
    job_url           TEXT,
    detail_url        TEXT,                   -- '더 알아보기' 상세페이지 링크
    is_closed         BOOLEAN,                -- 모집 종료 여부 (상세페이지에서 판별)
    summary           TEXT,                   -- LLM이 생성한 1~2줄 핵심 요약
    raw_text          TEXT,                   -- 파싱 전 메일 원문 (근거 보존용)
    parsed_json       JSONB,                  -- LLM 추출 결과 원본 (근거 보존용)
    received_at       TIMESTAMP,
    created_at        TIMESTAMP NOT NULL DEFAULT now(),

    UNIQUE (email_message_id, project_index)
);

-- 최근 공고 조회, 마감일 임박 조회 시 사용
CREATE INDEX IF NOT EXISTS idx_job_postings_received_at ON job_postings (received_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_postings_deadline ON job_postings (deadline);
CREATE INDEX IF NOT EXISTS idx_job_postings_is_closed ON job_postings (is_closed);


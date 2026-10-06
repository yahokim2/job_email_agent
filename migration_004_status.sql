-- 5단계: 대시보드의 관심/보류/거절 상태 저장용 컬럼
-- 실행: psql -d job_agent -f migration_004_status.sql

ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'new';
-- status 값: 'new'(미검토, 기본값) | 'interested'(관심) | 'hold'(보류) | 'rejected'(거절)

ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_job_postings_status ON job_postings (status);

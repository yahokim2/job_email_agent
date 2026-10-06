-- 대시보드의 "공고 삭제" 기능용: 행을 지우지 않고 삭제 시각만 기록(소프트 삭제)
-- 실행: psql -d job_agent -f migration_005_soft_delete.sql

ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_job_postings_deleted_at ON job_postings (deleted_at);

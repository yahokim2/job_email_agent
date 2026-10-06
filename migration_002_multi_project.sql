-- 2단계: 메일 하나에 여러 프로젝트가 들어가는 구조로 확장
-- 실행: psql -d job_agent -f migration_002_multi_project.sql

ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS project_index INTEGER NOT NULL DEFAULT 1;
ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS duties TEXT;
ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS expected_pay TEXT;
ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS start_date TEXT;
ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS expected_duration TEXT;
ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS detail_url TEXT;
ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS is_closed BOOLEAN;

-- 기존에는 이메일 하나당 행 하나(email_message_id UNIQUE)였지만,
-- 이제 이메일 하나에 프로젝트 여러 개 → (이메일, 프로젝트 순번) 조합으로 유니크해야 함
ALTER TABLE job_postings DROP CONSTRAINT IF EXISTS job_postings_email_message_id_key;
ALTER TABLE job_postings ADD CONSTRAINT job_postings_email_project_unique UNIQUE (email_message_id, project_index);

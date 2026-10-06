-- 3단계: RAG를 위한 벡터 저장소 도입
-- 사전 준비: brew install pgvector (터미널에서 먼저 실행)
-- 실행: psql -d job_agent -f migration_003_pgvector.sql

CREATE EXTENSION IF NOT EXISTS vector;

-- voyage-4-lite 모델을 512차원으로 사용 (비용·저장공간 절약, 이 프로젝트 규모엔 충분)
ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS embedding vector(512);

-- 코사인 유사도 검색 성능을 위한 인덱스 (데이터가 적을 땐 없어도 되지만 미리 만들어둠)
CREATE INDEX IF NOT EXISTS idx_job_postings_embedding
    ON job_postings USING hnsw (embedding vector_cosine_ops);

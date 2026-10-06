# 백엔드(메일 수집·파싱·임베딩·RAG 검색·리포트) 이미지
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 의존성 먼저 설치 → 소스만 바뀐 경우 이 단계는 캐시를 재사용 (빌드 속도)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사. 주의: .env(API 키)는 이미지에 넣지 않는다 (.dockerignore로 제외, 실행 시 주입)
COPY ingest.py search.py daily_report.py backfill_embeddings.py ./

# 기본 동작: 메일 수집 → 파싱 → 임베딩 → DB 저장
# 다른 스크립트는 컨테이너를 띄울 때 명령을 바꿔서 실행:
#   docker compose run --rm backend python search.py "여의도 Java"
CMD ["python", "ingest.py"]

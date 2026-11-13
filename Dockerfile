# Approval Planner 배포 이미지
# 1단계: 화면(frontend)을 빌드한다.
FROM node:22-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2단계: 서버(backend) + 빌드한 화면 + 원본 데이터
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv==0.12.10
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY 01_참가자_배포용/ /app/01_참가자_배포용/
COPY --from=web /app/frontend/dist /app/frontend/dist
# 실행 설정: 시연 모드(처음 DB를 만들 때만 적용), AI는 키 없이 도는 가짜 모드가 기본.
# 데이터는 컨테이너 안 SQLite라 다시 배포·재시작하면 처음 상태로 돌아간다(사용자 결정 2026-11-13).
ENV AXWAR_MODE=시연 \
    AXWAR_DB=/app/backend/var/axwar.db \
    PATH="/app/backend/.venv/bin:$PATH"
RUN mkdir -p /app/backend/var
EXPOSE 3000
# 작업자 1개: 엔진이 한 프로세스 안의 잠금으로 동시 요청을 막는다.
CMD ["sh", "-c", "exec uvicorn app.api.main:build_app --factory --host 0.0.0.0 --port ${PORT:-3000} --workers 1"]

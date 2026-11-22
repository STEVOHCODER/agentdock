FROM node:24-alpine AS frontend
WORKDIR /build
COPY package*.json ./
RUN npm install --no-audit --no-fund
COPY vite.config.js ./
COPY frontend ./frontend
RUN npm run build

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY backend ./backend
COPY backend/migrations ./backend/migrations
COPY cli ./cli
RUN pip install --no-cache-dir .
COPY --from=frontend /build/frontend/dist ./frontend/dist
COPY alembic.ini ./
COPY docs ./docs
RUN mkdir -p /app/data/skillvault && useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.agentdock.main:app --host 0.0.0.0 --port 8000"]

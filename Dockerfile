FROM node:24-slim AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci --legacy-peer-deps

COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

COPY requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt

COPY . ./
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

ENV PORT=8080
EXPOSE 8080

CMD uvicorn backend.api:app --host 0.0.0.0 --port ${PORT}

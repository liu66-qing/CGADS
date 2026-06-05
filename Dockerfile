FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway注入PORT环境变量，默认8000
ENV PORT=8000
EXPOSE ${PORT}

CMD uvicorn backend.api:app --host 0.0.0.0 --port ${PORT}

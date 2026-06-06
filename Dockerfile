FROM python:3.11-slim

WORKDIR /app

# 安装Node.js 18（Vite需要18+）
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制全部代码
COPY . .

# 构建前端（如果失败不阻断部署）
RUN cd frontend && npm install --legacy-peer-deps && npm run build || echo "WARN: frontend build failed, skipping"

# Railway注入PORT环境变量
ENV PORT=8080
EXPOSE ${PORT}

CMD uvicorn backend.api:app --host 0.0.0.0 --port ${PORT}

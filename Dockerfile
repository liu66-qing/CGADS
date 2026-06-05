FROM python:3.11-slim

WORKDIR /app

# 安装Node.js构建前端
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/*

# Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制全部代码
COPY . .

# 构建前端
RUN cd frontend && npm install && npm run build

# Railway注入PORT环境变量
ENV PORT=8080
EXPOSE ${PORT}

CMD uvicorn backend.api:app --host 0.0.0.0 --port ${PORT}

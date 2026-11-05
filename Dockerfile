# ============================================================
# FlowerUI 多阶段构建 Dockerfile
# ============================================================
# 阶段 1：Node.js 构建前端产物
# 阶段 2：Python 运行时，托管前端静态文件
# ============================================================

# ---------- 阶段 1：构建前端 ----------
FROM node:20-alpine AS frontend

WORKDIR /build

# 先复制依赖文件，利用 Docker 层缓存
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --registry=https://registry.npmmirror.com --no-audit --no-fund

# 复制源码并构建
COPY frontend/ ./
RUN npm run build

# ---------- 阶段 2：运行时 ----------
FROM python:3.12-slim

# 环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    FLOWER_HOST=0.0.0.0 \
    FLOWER_PORT=5555

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
# 本地开发统一用 `uv sync`（按 uv.lock 精确还原）；容器构建没有 uv，
# 这里仍走 pip + requirements.txt（不锁版本），因此镜像内依赖可能与本地不一致。
# 若需严格一致，可改为：COPY pyproject.toml uv.lock + uv sync --frozen。
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# 复制应用代码
COPY backend/app ./app

# 复制前端构建产物
COPY --from=frontend /build/dist ./static

# 暴露端口
EXPOSE 5555

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5555/healthcheck',timeout=4).status==200 else 1)"

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5555"]

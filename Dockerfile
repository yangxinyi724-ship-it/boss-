# boss- · 通用 Web 办公室镜像（含 Chromium）
# 使用说明：docs/docker.md
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PIP_DISABLE_PIP_VERSION_CHECK=1 \
	PIP_NO_CACHE_DIR=1 \
	PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
	BOSS_DATA_DIR=/data

WORKDIR /app

# Chromium 运行时依赖（与 patchright install-deps 对齐的常用库）
RUN apt-get update && apt-get install -y --no-install-recommends \
	ca-certificates \
	curl \
	fonts-liberation \
	libasound2 \
	libatk-bridge2.0-0 \
	libatk1.0-0 \
	libcups2 \
	libdbus-1-3 \
	libdrm2 \
	libgbm1 \
	libgtk-3-0 \
	libnspr4 \
	libnss3 \
	libx11-xcb1 \
	libxcomposite1 \
	libxdamage1 \
	libxfixes3 \
	libxkbcommon0 \
	libxrandr2 \
	xdg-utils \
	&& rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install -e ".[web]" \
	&& python -m patchright install chromium \
	&& mkdir -p /data

EXPOSE 8787

# 容器内必须监听 0.0.0.0；数据目录挂卷持久化
CMD ["boss", "--data-dir", "/data", "web", "--host", "0.0.0.0", "--port", "8787"]

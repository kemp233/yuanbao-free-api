# 1. 使用 Python 3.10 基础镜像
FROM python:3.10-slim

# 设置环境变量，防止 Python 产生 pyc 文件以及启用无头模式支持
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright

WORKDIR /app

# 2. 安装 OpenCV 和 Playwright 所需的最底层系统依赖
# 这些库是解决 libxcb.so.1 和 libGL.so.1 的关键
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libxcb1 \
    libx11-6 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libpango-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 3. 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. 【关键步骤】安装 Playwright 浏览器内核及其依赖
# 因为你在 Armbian (ARM64) 上，这一步会下载适配 ARM 的 Chromium
RUN python -m playwright install chromium
RUN python -m playwright install-deps chromium

# 5. 复制项目代码
COPY . .

# 暴露端口
EXPOSE 8000

# 启动程序
CMD ["python", "app.py"]

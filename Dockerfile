# 使用 Playwright 官方提供的 Python 环境基础镜像 (基于 Ubuntu Jammy)
# 该镜像已内置了浏览器运行所需的绝大部分系统依赖
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # 强制 Playwright 使用镜像内预装的浏览器路径
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# 1. 安装 OpenCV 可能缺少的额外系统库
# 虽然 playwright 镜像很全，但 OpenCV 有时仍需要 libgl1
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 2. 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple -r requirements.txt

# 3. 确保安装了 chromium 浏览器内核 (Playwright 专用)
# 虽然基础镜像带了浏览器，但执行此命令可以确保环境完整
RUN playwright install chromium

# 4. 复制项目代码
COPY . .

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "app.py"]

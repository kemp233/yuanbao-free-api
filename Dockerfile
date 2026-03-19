# 1. 使用你测试成功的镜像版本
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# 2. 设置环境变量（固化 API_KEY 和 浏览器路径）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # 固化你的 API Key
    API_KEYS=sk-123456 \
    # 强制使用全局浏览器路径，这是 Playwright 镜像的最佳实践
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# 3. 安装 OpenCV 运行所需的系统底层库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 4. 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple -r requirements.txt

# 5. 安装浏览器内核到指定路径
# 这一步会根据 ENV 中的路径安装到 /ms-playwright
RUN playwright install chromium

# 6. 复制项目代码
# 请确保你本地当前目录下的 browser_manager.py 是你修改后的那个“完美版”
COPY . .

# 7. (可选) 如果你本地的 browser_manager.py 不在当前根目录，
# 而是在 src/... 目录下，上面的 COPY . . 已经包含了它。
# 如果你想万无一失，可以再显式覆盖一次：
# COPY browser_manager.py ./src/services/browser/browser_manager.py

EXPOSE 8000

CMD ["python", "app.py"]

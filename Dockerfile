# 1. 使用 Python 3.10 基础镜像
FROM python:3.10-slim

# 设置环境变量，确保安装过程不弹出交互窗口
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 2. 只安装最基础的系统工具和 OpenCV 核心库
# libgl1 和 libglib2.0-0 是 OpenCV 运行的刚需
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libgl1 \
    libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 3. 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. 【核心修复】让 Playwright 自己安装它需要的系统依赖
# 这一步会自动补全你刚才报错中缺失的 libnss3, libatk 等几十个库
RUN python -m playwright install chromium
RUN python -m playwright install-deps chromium

# 5. 复制项目代码
COPY . .

# 暴露端口
EXPOSE 8000

# 启动程序
CMD ["python", "app.py"]

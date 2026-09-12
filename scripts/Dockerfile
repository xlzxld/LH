# 量化教程运行环境（可选）：不想装 Docker 也没关系，Windows 直接跑就行
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY code/ ./code/
COPY .env.example ./.env.example

# 非 root 运行（容器安全基线：进程被攻破时少一层权限）
RUN useradd -m quant && chown -R quant:quant /app
USER quant

# 默认运行 A 股监测机器人（一次性模式），实际用法见 docker-compose.yml
CMD ["python", "code/ch08_monitor/monitor_astock.py", "--once"]

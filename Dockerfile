# Complete KDD HR System with SearXNG and Redis
FROM python:3.11-slim

# Install system dependencies
RUN bash -c 'set -e; for i in 1 2 3; do \
        apt-get update -o Acquire::Retries::=3 && \
        apt-get install -y --no-install-recommends \
            curl redis-server supervisor git build-essential \
            libxml2-dev libxslt1-dev zlib1g-dev libjpeg-dev libffi-dev libssl-dev \
        && break || { echo "APT failed on attempt $i/3, retrying in 30s"; sleep 30; }; done' \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements file and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install SearXNG from source (correct way)
RUN git clone https://github.com/searxng/searxng.git /opt/searxng
WORKDIR /opt/searxng
# 预先安装 searxng 所需的所有依赖，避免运行时缺少模块
RUN pip install --no-cache-dir msgspec uvloop ujson brotli || true
RUN pip install --no-cache-dir -e .

# Create searxng user and directories
RUN groupadd --system --gid 991 searxng && \
    useradd --system --uid 991 --gid 991 --shell /bin/false --home-dir /usr/local/searxng searxng
RUN mkdir -p /etc/searxng /var/log/supervisor /usr/local/searxng
RUN chown -R searxng:searxng /usr/local/searxng

# Copy application code
WORKDIR /app
COPY . .

# Copy SearXNG configuration to correct location
COPY backend/searxng/config/settings.yml /etc/searxng/settings.yml
RUN chown searxng:searxng /etc/searxng/settings.yml

# Create supervisord configuration
RUN echo '[supervisord]\n\
nodaemon=true\n\
user=root\n\
logfile=/var/log/supervisor/supervisord.log\n\
pidfile=/var/run/supervisord.pid\n\
\n\
[program:redis]\n\
command=redis-server --daemonize no --port 6379\n\
autostart=true\n\
autorestart=true\n\
stderr_logfile=/var/log/supervisor/redis_stderr.log\n\
stdout_logfile=/var/log/supervisor/redis_stdout.log\n\
\n\
[program:searxng]\n\
command=python -m searx.webapp\n\
environment=SEARXNG_SETTINGS_PATH="/etc/searxng/settings.yml",PYTHONPATH="/opt/searxng",SEARXNG_DISABLE_IP_CHECK="1"\n\
directory=/opt/searxng\n\
autostart=true\n\
autorestart=true\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
user=searxng\n\
\n\
[program:streamlit]\n\
command=streamlit run app.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true --server.enableCORS=false --server.enableXsrfProtection=false --browser.gatherUsageStats=false\n\
directory=/app\n\
autostart=true\n\
autorestart=true\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
user=root' > /etc/supervisor/conf.d/supervisord.conf

# Set permissions
RUN chmod -R 755 /app
RUN chmod 644 /etc/searxng/settings.yml
RUN mkdir -p /var/log/supervisor
RUN chmod -R 755 /var/log/supervisor

# Expose ports
EXPOSE 8501 8080 6379

# Health check for Streamlit
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Start all services with supervisord
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
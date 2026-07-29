FROM python:3.13-slim

ARG BUILD_DATE
ENV BUILD_DATE=${BUILD_DATE:-}

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN adduser --disabled-password --gecos "" plates && \
    chown -R plates:plates /app

USER plates

RUN chmod +x entrypoint.sh

EXPOSE 9009

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9009/health')" || exit 1

ENTRYPOINT ["./entrypoint.sh"]

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=Africa/Cairo
RUN apt-get update && apt-get install -y --no-install-recommends tzdata ca-certificates && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 aipro
WORKDIR /app
COPY aipro ./aipro
RUN mkdir -p /app/data && chown aipro /app/data
USER aipro
ENV DB_PATH=/app/data/aipro.db WEB_HOST=0.0.0.0
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=3)"
CMD ["python", "-m", "aipro", "run"]

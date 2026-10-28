FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --system --uid 10001 seed
USER seed
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
LABEL org.opencontainers.image.source="https://github.com/stephenvidal/seed-os" \
      org.opencontainers.image.title="SEED API"
CMD ["uvicorn", "seed_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

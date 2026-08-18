# MultiOmics-Reactome v3.0 -- API / worker image
FROM python:3.11-slim-bookworm AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ gfortran libhdf5-dev libxml2-dev libxslt1-dev \
        libopenblas-dev liblapack-dev pkg-config curl git \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --upgrade pip wheel setuptools && \
    pip install --no-cache-dir "numpy>=2.0.0,<3.0.0" && \
    pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt

FROM python:3.11-slim-bookworm AS runtime
LABEL org.opencontainers.image.title="MultiOmics-Reactome" \
      org.opencontainers.image.version="3.0.0" \
      org.opencontainers.image.source="https://github.com/echimusa/MIMODH"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app OUTPUT_DIR=/app/output PORT=8000
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
        libhdf5-103 libxml2 libxslt1.1 libopenblas0 curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/lib/python3.11/site-packages \
                    /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY backend/ ./backend/
COPY schemas/ ./schemas/
COPY infra/   ./infra/
RUN mkdir -p /app/output && chmod 777 /app/output
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fs http://localhost:8000/health || exit 1
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.14-slim

ARG TARGETOS
ARG TARGETARCH
ARG VERSION=dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="ParseHub API" \
      org.opencontainers.image.description="Multi-platform social media resolver API and web UI" \
      org.opencontainers.image.source="https://github.com/wuuduf/parsehub-api" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir ".[api,object-storage]"

RUN useradd --create-home --uid 10001 parsehub
RUN mkdir -p /data && chown parsehub:parsehub /data
USER parsehub

EXPOSE 8000
ENV PARSEHUB_CONTAINER_ARCH="${TARGETOS}/${TARGETARCH}"
CMD ["uvicorn", "parsehub_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UNIKEGG_HOME=/app \
    UNIKEGG_DATA_DIR=/data

WORKDIR /app
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY db ./db
RUN pip install --no-cache-dir --no-deps . \
    && groupadd --gid 10001 unikegg \
    && useradd --uid 10001 --gid unikegg --no-create-home unikegg \
    && mkdir -p /app/artifacts \
    && chown unikegg:unikegg /app/artifacts

USER 10001:10001
ENTRYPOINT ["unikegg"]
CMD ["load"]

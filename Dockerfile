FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir --disable-pip-version-check .

# Use a non-root user. Mounted /data must be writable by UID 10001.
RUN useradd --system --uid 10001 --home /app purr && mkdir -p /data && chown -R 10001:10001 /data /app
USER 10001

EXPOSE 8080
CMD ["python", "-m", "purrfect.deploy", "gateway"]

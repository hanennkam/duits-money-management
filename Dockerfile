FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so the layer is reused while app/ changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Never run the API as root.
RUN useradd --create-home --uid 10001 appuser
USER appuser

# Informational only; the host decides the real mapping.
EXPOSE 8000

# exec so uvicorn is PID 1 and receives SIGTERM for a clean shutdown.
# Every secret comes from the environment at runtime — nothing is baked into the image.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

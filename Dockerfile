FROM python:3.12-slim AS api

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv pip install --no-cache .

EXPOSE 8000
CMD ["uvicorn", "seldon.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

ARG UV_DEFAULT_INDEX=https://pypi.org/simple
ARG UV_VERSION=0.11.26
ENV UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX}

WORKDIR /app

RUN pip install --no-cache-dir --index-url ${UV_DEFAULT_INDEX} "uv==${UV_VERSION}"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

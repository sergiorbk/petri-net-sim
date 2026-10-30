FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY vendor/petri-modeling-skills/ vendor/petri-modeling-skills/
RUN uv sync --frozen --no-dev

COPY . .
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]

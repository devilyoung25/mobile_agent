FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY . .
RUN uv sync --no-dev

EXPOSE 4001
CMD ["uv", "run", "uvicorn", "model_gateway.app:app", "--host", "0.0.0.0", "--port", "4001"]

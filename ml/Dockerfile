FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY lisa_ml ./lisa_ml

RUN pip install --no-cache-dir .

CMD ["lisa-ml-retrain"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY app ./app

EXPOSE 8000

USER 65532:65532

CMD ["uvicorn", "app.http_app:app", "--host", "0.0.0.0", "--port", "8000"]

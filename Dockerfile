FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 botuser && mkdir -p /app/data /app/temp /app/downloads && chown -R botuser:botuser /app
USER botuser

CMD ["python", "main.py"]

FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY scripts ./scripts
COPY data ./data
COPY main.py .

# Secrets come from the host env / platform dashboard. Do not bake .env into the image.
CMD ["python", "scripts/paper_live.py"]

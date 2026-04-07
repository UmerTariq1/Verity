FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg2 and pdfplumber
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY constraints.txt .
# Install CPU-only PyTorch in its own layer so it stays cached when app deps change.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu -c constraints.txt torch

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

COPY . .

# data/ is mounted as a volume in docker-compose; this COPY is a fallback for
# standalone image builds so the directory always exists inside the container.
RUN mkdir -p /app/data

EXPOSE 8000

RUN chmod +x /app/entrypoint.sh
CMD ["/app/entrypoint.sh"]

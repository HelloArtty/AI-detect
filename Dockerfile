FROM python:3.8-slim

WORKDIR /app

COPY . /app

COPY ai-rec-450910-e6d7e520d2bd.json /app

# Install system dependencies for psycopg2
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

# Define environment variable
ENV NAME=World


EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

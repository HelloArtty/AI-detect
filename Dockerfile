FROM python:3.9-slim

WORKDIR /app

COPY . .


# Install system dependencies for psycopg2
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN ls -l /app/requirements.txt && cat /app/requirements.txt

RUN pip install --upgrade pip && pip install -r requirements.txt

# Define environment variable
ENV NAME=World
ENV PORT=8080
# Run the application using uvicorn
CMD ["python", "detect.py"]

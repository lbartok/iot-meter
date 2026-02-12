FROM python:3.13-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY collector.py .

# Expose health check port
EXPOSE 8081

# Run the collector
CMD ["python", "-u", "collector.py"]

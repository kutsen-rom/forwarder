FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose port for HTTP health checks
EXPOSE 8000

CMD ["python", "forwarder.py"]
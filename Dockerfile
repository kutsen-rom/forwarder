FROM python:3.9-slim

WORKDIR /app

# Install dependencies first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY forwarder.py .
COPY keywords_config.py .

# Create non-root user for security
RUN useradd -m -u 1000 telegrambot && \
    chown -R telegrambot:telegrambot /app

USER telegrambot

CMD ["python", "forwarder.py"]
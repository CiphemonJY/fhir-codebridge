FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code, config, and client SDK
COPY scripts/ scripts/
COPY data/ data/
COPY config/ config/
COPY codebridge/ codebridge/
COPY pyproject.toml .

# Create non-root user for security
RUN useradd -m -s /bin/bash codebridge && \
    chown -R codebridge:codebridge /app
USER codebridge

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run the server
CMD ["uvicorn", "scripts.api.server:app", "--host", "0.0.0.0", "--port", "8000"]

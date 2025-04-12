FROM python:3.11-slim

WORKDIR /app

# Install build tools if needed for some Python packages (uncomment if required)
# RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies directly in the final image
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy application files (adjust as needed)
COPY prompts.yaml /app/prompts.yaml
# COPY src/ /app/src/
# COPY frontend/ /app/frontend/

# Expose the port the application runs on
EXPOSE 8051

# Set the default command to run the application
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8051", "--reload"]

# Optional healthcheck
# HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
#   CMD curl -f http://localhost:8051/health || exit 1
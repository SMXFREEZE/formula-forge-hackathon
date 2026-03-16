FROM python:3.10-slim

WORKDIR /app

# Install Node.js and system dependencies for pyttsx3 (espeak)
RUN apt-get update && apt-get install -y --no-install-recommends curl espeak && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY requirements.txt .
COPY package.json .
COPY package-lock.json .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Node.js dependencies
RUN npm ci --production

# AWS credentials (set at runtime via -e or Render dashboard)
# ENV AWS_ACCESS_KEY_ID=""
# ENV AWS_SECRET_ACCESS_KEY=""

# Copy application code
COPY app.py .
COPY formula_forge.py .
COPY generate_slides.js .

# Copy static frontend
COPY index.html ./index.html

# Create outputs directory
RUN mkdir -p /app/outputs

# Expose the API port
EXPOSE 8000

# Start Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

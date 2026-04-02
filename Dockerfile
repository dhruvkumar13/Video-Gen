FROM python:3.10-slim

# System deps: ffmpeg, Node.js 20, build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Remotion dependencies
COPY remotion/package.json remotion/package-lock.json* remotion/
RUN cd remotion && npm install --production=false 2>/dev/null; exit 0

# Copy app code
COPY . .

# Pre-build Remotion bundle (speeds up first render)
RUN cd remotion && npx remotion bundle src/index.ts --out-dir=bundle 2>/dev/null; exit 0

# Create jobs directory
RUN mkdir -p jobs

EXPOSE ${PORT:-4000}

CMD gunicorn server:app \
    --bind 0.0.0.0:${PORT:-4000} \
    --workers 2 \
    --threads 4 \
    --timeout 600 \
    --access-logfile -

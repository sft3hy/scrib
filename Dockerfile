# Stage 1: Build the React frontend
FROM node:20-alpine AS build-stage
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Python environment
FROM python:3.10

# Copy FFmpeg static binaries (no apt-get or network package downloads required)
COPY --from=mwader/static-ffmpeg:7.0 /ffmpeg /usr/local/bin/
COPY --from=mwader/static-ffmpeg:7.0 /ffprobe /usr/local/bin/

# Install standard system libraries to support screen recording dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    libxcb-randr0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Copy built frontend assets from stage 1 into our static dist folder
COPY --from=build-stage /frontend/dist /app/frontend/dist

# Expose port 3001 for the unified FastAPI + React UI
EXPOSE 3001

# Start the unified FastAPI server
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "3001"]

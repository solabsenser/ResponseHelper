FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-rus \
    libtesseract-dev \
    libleptonica-dev \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    libavfilter-dev \
    libswresample-dev \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    wget \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create volume for temporary files
VOLUME ["/tmp"]

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the bot
CMD ["python", "bot.py"]

ARG BUILD_FROM=python:3.11-slim
FROM $BUILD_FROM

# Install ALSA, ffmpeg for audio processing, and python3
RUN apt-get update && apt-get install -y \
    alsa-utils \
    ffmpeg \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

# Install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app logic
COPY run.py ./

# Run the script
CMD [ "python", "-u", "./run.py" ]

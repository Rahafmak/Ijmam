FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-cv.txt ./

# Base app only. Add requirements-cv.txt for the camera screen - it pulls in
# torch and adds roughly 2 GB, which most free tiers will not build.
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV HOST=0.0.0.0 PORT=7860
EXPOSE 7860
CMD ["python", "app.py"]

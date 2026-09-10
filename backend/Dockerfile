FROM python:3.11-slim

# ffmpeg 用于合成导出
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-noto-cjk && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY pyproject.toml .
COPY app ./app
COPY workflows ./workflows
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

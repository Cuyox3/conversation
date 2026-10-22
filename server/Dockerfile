FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY python python
COPY server server
# Acepta la licencia CPML de XTTS-v2 (uso no comercial)
ENV COQUI_TOS_AGREED=1 CONVERSION_VOCES=/data/voces
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]

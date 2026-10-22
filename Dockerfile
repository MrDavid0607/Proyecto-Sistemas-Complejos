FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN pip install --no-cache-dir psutil numpy

COPY src ./src

# Cada contenedor es un nodo; su configuración llega por variables de entorno
# (NODE_ID, BROADCAST_ADDRESS, BANDWIDTH_MBPS, HTTP_PORT, LOG_DIR...).
CMD ["python", "-m", "complexnet"]

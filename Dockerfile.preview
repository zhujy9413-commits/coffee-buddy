FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# Explicit source list: no .env, local records, trajectories or access files.
COPY cloud_preview.py web_app.py web_core.py map_location.py ./
COPY web/index.html web/app.js web/style.css web/location.js web/amap-location.js ./web/
USER 10001:10001
CMD ["python", "cloud_preview.py"]

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# Explicit source list: no .env, local records, trajectories or access files.
COPY docker_entrypoint.py cloud_preview.py cloud_storage.py storage_backup.py web_app.py web_core.py map_location.py ./
COPY web/index.html web/app.js web/style.css web/location.js web/amap-location.js web/journal.js web/menu-drafts.js web/menu-batch.js ./web/
# The entrypoint creates the private disk subdirectory and drops all root
# privileges before opening the database or accepting any HTTP connections.
CMD ["python", "docker_entrypoint.py"]

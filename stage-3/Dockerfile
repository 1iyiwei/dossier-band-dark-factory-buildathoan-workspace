# Dossier stage 1: a single-container HTTP service. Every dependency is installed at
# build time; at run time the only outbound traffic is to the provider endpoints.
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PORT=8080 PYTHONUNBUFFERED=1 DOSSIER_DATA_DIR=/srv/data
EXPOSE 8080
CMD ["python", "-m", "app"]

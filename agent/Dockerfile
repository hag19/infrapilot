# InfraPilot agent image. Build + push, then reference from
# kubernetes/agent/deployment.yaml.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY infrapilot/ ./infrapilot/

# Default: run a one-shot health sweep. Override args to diagnose a symptom,
# or run as a long-lived job/cron via the K8s manifests.
ENTRYPOINT ["python", "-m", "infrapilot"]

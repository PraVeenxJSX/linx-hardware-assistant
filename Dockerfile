# Optional Linux container demo. Hardware visibility depends on host device mounts.
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends util-linux pciutils dmidecode procps && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENTRYPOINT ["python","-m","hardware_assistant.cli"]
CMD ["chat"]

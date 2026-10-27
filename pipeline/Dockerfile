FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Reads and writes /data (mounted from ./data in docker-compose.yml)
CMD ["python", "-m", "s2r.run"]

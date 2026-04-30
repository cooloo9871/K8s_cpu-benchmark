FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libnuma1 libnuma-dev && rm -rf /var/lib/apt/lists/*
RUN pip install flask numpy --no-cache-dir
COPY app.py .
EXPOSE 8080
CMD ["python", "app.py"]

FROM python:3.11-slim

WORKDIR /app

RUN mkdir -p /app/public

COPY server.py /app/server.py
COPY index.html /app/public/index.html

EXPOSE 3000

CMD ["python", "/app/server.py"]

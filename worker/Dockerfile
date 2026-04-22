FROM python:3.11-slim
WORKDIR /app
RUN pip install flask numpy --no-cache-dir
COPY app.py .
EXPOSE 8080
CMD ["python", "app.py"]

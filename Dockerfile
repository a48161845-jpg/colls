FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV DB_PATH=/data/ashen_realm.sqlite3
VOLUME /data
CMD ["python", "-m", "bot"]

FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY oyoyo_mcp_server/server.py .
EXPOSE 9000
CMD ["python", "server.py"]

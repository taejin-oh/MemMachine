# Development stand-in for the vLLM chat and embedding servers (mock_llm.py).
FROM python:3.12-slim
RUN pip install --no-cache-dir "fastapi==0.115.12" "uvicorn==0.34.2"
WORKDIR /app
COPY mock_llm.py .
EXPOSE 8000
CMD ["uvicorn", "mock_llm:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.14-slim
RUN pip install --no-cache-dir "httpx>=0.27,<1" "langgraph>=1,<2" "langgraph-checkpoint-sqlite>=3,<4"
WORKDIR /workspace
ENV PYTHONPATH=/workspace/src
CMD ["python", "-m", "purrfect.local_api"]

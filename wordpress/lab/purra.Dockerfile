FROM python:3.14-slim
RUN pip install --no-cache-dir "httpx>=0.27,<1"
WORKDIR /workspace
ENV PYTHONPATH=/workspace/src
CMD ["python", "-m", "purrfect.local_api"]

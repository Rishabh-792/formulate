FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY formulate/ formulate/
COPY api/ api/
COPY ui/ ui/
COPY examples/ examples/
COPY prompts/ prompts/

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

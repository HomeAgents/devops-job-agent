FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install chromium

COPY job_agent ./job_agent
COPY orchestrator ./orchestrator
COPY run.py run_orchestrator.py ./
COPY config.browser.example.json ./config.json

ENV ORCHESTRATOR_DATA_DIR=/work
ENV JOB_AGENT_CONFIG=/work/config.json

ENTRYPOINT ["python3", "run.py"]
CMD ["--config", "/work/config.json", "--db", "/work/jobs.db", "--email-all-fetched"]

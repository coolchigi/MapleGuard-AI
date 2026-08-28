# MapleGuard advisor — Amazon Bedrock AgentCore Runtime container.
#
# AgentCore Runtime requires a linux/arm64 image that serves the agent on port 8080 (the
# BedrockAgentCoreApp exposes the /invocations + /ping contract via app.run()). `agentcore
# launch` can build this for you; this Dockerfile makes the build explicit and reproducible.
#
# Build + run locally (the same contract AgentCore invokes):
#   docker build --platform linux/arm64 -t mapleguard-advisor server/
#   docker run --platform linux/arm64 -p 8080:8080 \
#     -e AWS_REGION=us-east-1 mapleguard-advisor
#   curl -s localhost:8080/ping

FROM --platform=linux/arm64 python:3.12-slim

WORKDIR /app

# Install deps first for layer caching. The deterministic core needs no deps; these are for the
# agent + AgentCore + model calls (see requirements.txt).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The server package tree (crs/pnp/paths/noc/ingest/agent/api). PYTHONPATH=/app mirrors the
# repo's `cd server && PYTHONPATH=.` so `from crs import ...` resolves.
COPY . /app
# Memory defaults to the seeded offline corpus (config.Deployment). Set
# MAPLEGUARD_MEMORY_BACKEND=bedrock_kb + MAPLEGUARD_KB_ID at launch to use a live KB.
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Runs BedrockAgentCoreApp.run() -> the /invocations + /ping server on 8080.
CMD ["python", "-m", "agent.agentcore_app"]

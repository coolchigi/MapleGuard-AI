"""AWS Lambda entrypoint for the FastAPI API (behind a Lambda Function URL).

This is the deploy counterpart to `api/asgi.py` (`uvicorn api.asgi:app` for local). Mangum adapts
the same ASGI app to the Lambda invoke/Function-URL event, so the deployed web frontend gets a
real HTTPS backend with no separate container or ECR — coherent with the monitor Lambda in
`infra/`. The app is built once at cold start from the environment: it wires the NOC model
(Bedrock, per model_config) and the profile store (DynamoDB, since MAPLEGUARD_PROFILES_TABLE is
set on the deployed function), so `/profiles`, `/audit`, `/draws`, and the compute endpoints all
work against the same stores the monitor uses.

`mangum` is a deploy-only dependency (in requirements.txt); this module is imported only inside
the API Lambda, never by the package __init__ or the tests.
"""
from mangum import Mangum

from .app import create_app

app = create_app()
handler = Mangum(app)

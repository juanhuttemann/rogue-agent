"""Chat client settings and model wiring."""

import os

from agent_framework.openai import OpenAIChatCompletionClient
from dotenv import load_dotenv

# Explicit process variables take precedence over local development defaults.
load_dotenv()

MAX_TOOL_CALLS = 20

# Transient model-server failures (e.g. 503 while a local model loads) are
# retried with exponential backoff before a scenario gives up.
RETRY_ATTEMPTS = 6
RETRY_BASE_DELAY = 5  # seconds; doubles per attempt


def build_client() -> OpenAIChatCompletionClient:
    client = OpenAIChatCompletionClient(
        model=os.environ["OPENAI_MODEL"],
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
    )
    # Bounds the framework's tool-call loop (total run_python calls per run).
    client.function_invocation_configuration["max_function_calls"] = MAX_TOOL_CALLS
    return client


def default_options() -> dict:
    # Reasoning models that emit <think> need a higher token budget to finish;
    # set OPENAI_MAX_TOKENS in .env. Omit it for plain chat models.
    opts: dict = {}
    if v := os.environ.get("OPENAI_MAX_TOKENS"):
        opts["max_tokens"] = int(v)
    return opts

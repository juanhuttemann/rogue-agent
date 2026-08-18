"""Execute agent-written Python in an isolated OpenSandbox container."""

import asyncio
import os
import subprocess
from datetime import timedelta
from typing import Annotated
from urllib.parse import urlparse
from urllib.request import urlopen

from agent_framework import tool
from dotenv import load_dotenv
from opensandbox import Sandbox
from opensandbox.config.connection import ConnectionConfig
from opensandbox.models import WriteEntry
from opensandbox.models.execd import RunCommandOpts

CODE_PATH = "/tmp/code.py"
load_dotenv()
IMAGE = "python:3.12"
TIMEOUT = timedelta(minutes=30)
CMD_TIMEOUT = timedelta(seconds=120)


class SandboxUnavailableError(ConnectionError):
    """Raised when the configured OpenSandbox server cannot be reached."""


def sandbox_connection() -> ConnectionConfig:
    return ConnectionConfig(
        api_key=os.environ["OPENSANDBOX_API_KEY"],
        domain=os.environ.get("OPENSANDBOX_DOMAIN", "127.0.0.1:8080"),
        protocol=os.environ.get("OPENSANDBOX_PROTOCOL", "http"),
        # The server runs on the host and each sandbox publishes its ports, so
        # the demo reaches sandbox endpoints directly — no server-side proxy.
        use_server_proxy=False,
    )


def sandbox_server_url() -> str:
    protocol = os.environ.get("OPENSANDBOX_PROTOCOL", "http")
    domain = os.environ.get("OPENSANDBOX_DOMAIN", "127.0.0.1:8080")
    return f"{protocol}://{domain}"


async def ensure_sandbox_server_reachable(timeout: float = 3.0) -> None:
    parsed = urlparse(sandbox_server_url())
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        raise SandboxUnavailableError("OPENSANDBOX_DOMAIN is invalid")

    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, TimeoutError) as e:
        raise SandboxUnavailableError(str(e)) from e

    writer.close()
    await writer.wait_closed()


async def preflight() -> None:
    """Refuse to run until the documented containment prerequisites pass."""
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SandboxUnavailableError(
            "Preflight failed: Docker is unavailable or its socket cannot be accessed.\n\n"
            "Next agent: follow README.md exactly. Start Docker, ensure the current user can "
            "run `docker info`, then start the documented OpenSandbox server. "
            "Do not substitute a direct model/API test."
        ) from e
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:]
        suffix = f" Detail: {detail[0]}" if detail else ""
        raise SandboxUnavailableError(
            "Preflight failed: Docker is not accessible." + suffix + "\n\n"
            "Next agent: follow README.md exactly. Fix Docker access, then verify with `docker info`. "
            "Do not run scenarios through another harness."
        )

    health_url = f"{sandbox_server_url()}/health"
    try:
        await asyncio.to_thread(urlopen, health_url, timeout=3)
    except Exception as e:
        raise SandboxUnavailableError(
            f"Preflight failed: OpenSandbox health check did not pass at {health_url}.\n\n"
            "Next agent: start the OpenSandbox server using the README.md command, "
            "verify `curl http://127.0.0.1:8080/health`, and retry. Do not substitute a "
            "direct model/API test."
        ) from e


async def create_sandbox() -> Sandbox:
    # One long-lived container; the tool reuses it across calls.
    await ensure_sandbox_server_reachable()
    return await Sandbox.create(
        IMAGE,
        timeout=TIMEOUT,
        connection_config=sandbox_connection(),
    )


def make_run_python(sb: Sandbox, on_result=None):
    # Bind run_python to one long-lived sandbox so the container is reused across calls.
    # `on_result(code, exit_code, output)` is called after every execution (for reporting).
    @tool
    async def run_python(code: Annotated[str, "Python source code to execute"]) -> str:
        """Run Python source in the isolated sandbox; return stdout, stderr, and exit_code."""
        await sb.files.write_files([WriteEntry(path=CODE_PATH, data=code, mode=0o644)])
        ex = await sb.commands.run(f"python {CODE_PATH}", opts=RunCommandOpts(timeout=CMD_TIMEOUT))
        output = ("\n".join(l.text for l in ex.logs.stdout) + "\n" + "\n".join(l.text for l in ex.logs.stderr)).strip()
        exit_code = ex.exit_code if ex.exit_code is not None else 1
        if on_result:
            on_result(code, exit_code, output)
        return f"[exit_code={exit_code}]\n{output}"

    return run_python

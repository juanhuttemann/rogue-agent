"""Execute agent-written Python in an isolated OpenSandbox container."""

import asyncio
import os
from datetime import timedelta
from typing import Annotated
from urllib.parse import urlparse

from agent_framework import tool
from dotenv import load_dotenv
from opensandbox import Sandbox
from opensandbox.config.connection import ConnectionConfig
from opensandbox.models import WriteEntry
from opensandbox.models.execd import RunCommandOpts
from opensandbox.models.sandboxes import Host, Volume

CODE_PATH = "/tmp/code.py"
load_dotenv()
IMAGE = "python:3.12"
TIMEOUT = timedelta(minutes=30)
CMD_TIMEOUT = timedelta(seconds=120)
# Hard disk cap for the sandbox: the Docker runtime has no per-container storage
# quota (ext4 host), so agent disk-fill attacks would otherwise hit the HOST disk.
# A 2GB loopback ext4 image bind-mounted at /tmp is the filesystem-level ceiling.
DISK_IMG = "/var/tmp/rogue-sandbox.img"
DISK_MNT = "/mnt/rogue-sandbox"


class SandboxUnavailableError(ConnectionError):
    """Raised when the configured OpenSandbox server cannot be reached."""


def ensure_disk() -> None:
    # Idempotent one-time setup (needs passwordless sudo); survives until reboot.
    if os.path.ismount(DISK_MNT):
        return
    import subprocess
    subprocess.run(
        ["sudo", "-n", "bash", "-c",
         f"mkdir -p {DISK_MNT}; [ -f {DISK_IMG} ] || truncate -s 2G {DISK_IMG}; "
         f"[ -f {DISK_IMG}.fs ] || {{ mkfs.ext4 -q -F {DISK_IMG} && touch {DISK_IMG}.fs; }}; "
         f"mount -o loop {DISK_IMG} {DISK_MNT}; chmod 777 {DISK_MNT}"],
        check=True,
    )


def sandbox_connection() -> ConnectionConfig:
    return ConnectionConfig(
        api_key=os.environ["OPENSANDBOX_API_KEY"],
        domain=os.environ.get("OPENSANDBOX_DOMAIN", "localhost:8080"),
        protocol=os.environ.get("OPENSANDBOX_PROTOCOL", "http"),
        # The server is containerized, so use its proxy for sandbox endpoints
        # that are not directly reachable from the host.
        use_server_proxy=True,
    )


def sandbox_server_url() -> str:
    protocol = os.environ.get("OPENSANDBOX_PROTOCOL", "http")
    domain = os.environ.get("OPENSANDBOX_DOMAIN", "localhost:8080")
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


async def create_sandbox() -> Sandbox:
    # One long-lived container; the tool reuses it across calls.
    await ensure_sandbox_server_reachable()
    ensure_disk()
    return await Sandbox.create(
        IMAGE,
        timeout=TIMEOUT,
        connection_config=sandbox_connection(),
        volumes=[Volume(name="scratch", host=Host(path=DISK_MNT), mount_path="/tmp")],
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

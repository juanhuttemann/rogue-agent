"""Crescendo demo: a benign agent steered turn-by-turn into destructive code.

The agent's instructions stay benign the whole time; only the user turns
escalate. The sandbox is the only thing between the resulting code and the host.
Watch the submitted code drift from benign ops work to disk-fill, credential
exfiltration, and recursive deletion.
"""

import asyncio
import os
import sys

from agent_framework import Agent, AgentSession
from agent_framework.exceptions import ChatClientException
from opensandbox.exceptions import SandboxException
from opensandbox.models import WriteEntry
from rich.console import Console
from rich.panel import Panel

from .reporting import Reporter
from .sandbox import SandboxUnavailableError, create_sandbox, make_run_python, preflight
from .scenarios import (
    BASELINE_TASK,
    DELETION_FIXTURES,
    DELETION_TURNS,
    DISK_FILL_TURNS,
    EXFILTRATION_TURNS,
    INSTRUCTIONS,
    LOG_FIXTURE,
)
from .settings import RETRY_ATTEMPTS, RETRY_BASE_DELAY, build_client, default_options

SCENARIOS = [
    ("baseline", [BASELINE_TASK], [LOG_FIXTURE]),
    ("crescendo: disk-fill", DISK_FILL_TURNS, [LOG_FIXTURE]),
    ("crescendo: exfiltration", EXFILTRATION_TURNS, [LOG_FIXTURE]),
    ("crescendo: deletion", DELETION_TURNS, DELETION_FIXTURES),
]


async def run_turn(agent: Agent, reporter: Reporter, turn: str, session: AgentSession):
    # Local model servers 503 while loading; back off and retry before giving up.
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return await agent.run(turn, session=session)
        except ChatClientException as e:
            if attempt == RETRY_ATTEMPTS:
                raise
            delay = RETRY_BASE_DELAY * 2 ** (attempt - 1)
            reporter.note(f"model server error, retrying {attempt}/{RETRY_ATTEMPTS - 1} in {delay}s: {e.__cause__ or e}")


async def run_scenario(reporter: Reporter, name: str, turns: list[str], fixtures: list[tuple[str, str]]) -> None:
    sb = await create_sandbox()
    reporter.scenario(name)
    try:
        await sb.files.write_files([WriteEntry(path=path, data=data, mode=0o644) for path, data in fixtures])
        agent = Agent(
            client=build_client(),
            name="OpsAssistant",
            instructions=INSTRUCTIONS,
            tools=[make_run_python(sb, on_result=reporter.execution)],
            default_options={**default_options(), "tool_choice": "required"},
        )
        session = AgentSession()
        for i, turn in enumerate(turns, 1):
            reporter.turn(i, turn)
            resp = await run_turn(agent, reporter, turn, session)
            reporter.assistant((resp.text or "").strip())
    finally:
        await sb.kill()


def select(argv: list[str]) -> list[tuple[str, list[str], list[tuple[str, str]]]]:
    # Substring match, e.g. `python -m rogue_agent exfil deletion`. No args = all.
    if not argv:
        return SCENARIOS
    selected = [s for s in SCENARIOS if any(a in s[0] for a in argv)]
    unknown = [a for a in argv if not any(a in s[0] for s in selected)]
    if unknown:
        from rich.console import Console
        Console().print(f"no scenario matches {unknown}; available: {[s[0] for s in SCENARIOS]}")
        sys.exit(2)
    return selected


async def main() -> int:
    selected = select(sys.argv[1:])
    reporter = Reporter("attack_transcript.md")
    try:
        await preflight()
        for name, turns, fixtures in selected:
            try:
                await run_scenario(reporter, name, turns, fixtures)
            except ChatClientException as e:
                reporter.error(f"scenario '{name}' skipped — model server unreachable: {e.__cause__ or e}")
    except (SandboxUnavailableError, SandboxException) as e:
        if os.environ.get("ROGUE_DEBUG"):
            raise
        message = str(e)
        Console(stderr=True).print(Panel(message, title="OpenSandbox unavailable", border_style="red"))
        return 1
    finally:
        reporter.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\ninterrupted — sandbox killed, transcript saved")
        sys.exit(130)

"""Terminal and transcript reporting for the demo.

Terminal: rich (rules, panels, syntax-highlighted code).
Transcript: plain text mirror, one role-tagged block per event.
"""

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

console = Console()


class Reporter:
    def __init__(self, transcript_path: str):
        self._transcript_path = transcript_path
        self._f = None

    def _file(self):
        # Delay truncating the previous transcript until a scenario really starts.
        if self._f is None:
            self._f = open(self._transcript_path, "w")
        return self._f

    def _both(self, terminal, file_text: str) -> None:
        console.print(terminal)
        self._file().write(file_text + "\n")

    def scenario(self, name: str) -> None:
        console.rule(f"[bold cyan]{name}")
        self._file().write(f"\n{'=' * 70}\n{name}\n{'=' * 70}\n")

    def turn(self, i: int, text: str) -> None:
        console.print(f"\n[bold yellow]\\[ turn #{i} ][/] {text}")
        self._file().write(f"\n[USER] {text}\n")

    def code(self, code: str) -> None:
        self._both(Panel(Syntax(code, "python", word_wrap=True), title="run_python"), f"[CODE]\n{code}")

    def result(self, exit_code: int, output: str) -> None:
        color = "green" if exit_code == 0 else "red"
        panel = Panel(output or "(no output)", title=f"exit_code={exit_code}", border_style=color)
        self._both(panel, f"[RESULT exit_code={exit_code}]\n{output}")

    def execution(self, code: str, exit_code: int, output: str) -> None:
        self.code(code)
        self.result(exit_code, output)

    def assistant(self, text: str) -> None:
        self._both(Panel(text or "(no text)"), f"[ASSISTANT] {text}\n")

    def note(self, text: str) -> None:
        console.print(f"[yellow]{text}[/]")
        self._file().write(f"[NOTE] {text}\n")

    def error(self, text: str) -> None:
        self._both(Panel(text, border_style="red"), f"[ERROR] {text}\n")

    def close(self) -> None:
        if self._f is not None:
            self._f.close()

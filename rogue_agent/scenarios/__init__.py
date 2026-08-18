"""All scenario text in one place: agent instructions, user turns, fixtures.

Edit the files under attacks/ to tune the demo. Turns are separated by a `---`
line; files under fixtures/ are copied verbatim into the sandbox at the same
relative path under /tmp.
"""

from pathlib import Path

_DIR = Path(__file__).parent
_ATTACKS = _DIR / "attacks"
_FIXTURES = _DIR / "fixtures"


def _text(name: str) -> str:
    return (_DIR / name).read_text().strip()


def _attack(name: str) -> list[str]:
    return [t.strip() for t in (_ATTACKS / name).read_text().strip().split("\n---\n")]


def _fixture_files() -> list[tuple[str, str]]:
    return [
        (str(Path("/tmp") / p.relative_to(_FIXTURES)), p.read_text())
        for p in sorted(_FIXTURES.rglob("*"))
        if p.is_file()
    ]


LOG_PATH = "/tmp/access.log"
LOG_FIXTURE = (LOG_PATH, (_FIXTURES / "access.log").read_text().strip())
INSTRUCTIONS = _text("INSTRUCTIONS.md")
BASELINE_TASK = _text("baseline.txt")

# Each attack is a crescendo: benign opener, small defensible escalations that
# lean on the model's own output, then a final "you already did X" push.
DISK_FILL_TURNS = _attack("disk_fill.txt")
EXFILTRATION_TURNS = _attack("exfiltration.txt")
DELETION_TURNS = _attack("deletion.txt")

DELETION_FIXTURES = [LOG_FIXTURE, *_fixture_files()]

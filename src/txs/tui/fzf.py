"""fzf picker used by the TUI's `/` key.

The TUI hands the terminal to fzf (via ``App.suspend``) and resumes once it
exits, so the picker is full-screen rather than embedded in a panel.
"""

from __future__ import annotations

import shutil
import subprocess

from rich.text import Text

from txs.config import get_txs_setting


def fzf_available() -> bool:
    return shutil.which("fzf") is not None


def plain_label(label: str | Text) -> str:
    """Strip Rich markup from a tree label so fzf shows plain text."""
    if isinstance(label, Text):
        return label.plain
    return Text.from_markup(str(label)).plain


def run_fzf_pick(labels: list[str], header: str, prompt: str) -> int | None:
    """Show ``labels`` in fzf; return the chosen index, or None if cancelled.

    Each input line is ``<index>\\t<label>``; fzf displays only the label and
    returns the full line, so the index comes back unambiguously.
    """
    if not labels:
        return None
    lines = "\n".join(f"{i}\t{label}" for i, label in enumerate(labels))
    result = subprocess.run(
        [
            "fzf",
            "--no-print-query",
            "--delimiter=\t",
            "--with-nth=2..",
            f"--header={header}",
            f"--prompt={prompt}",
            f"--height={get_txs_setting('fzf_height') or '50%'}",
            "--layout=reverse",
            "--border",
        ],
        input=lines,
        text=True,
        check=False,
        stdout=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None
    chosen = result.stdout.split("\t", 1)[0].strip()
    return int(chosen) if chosen.isdigit() else None

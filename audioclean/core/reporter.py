from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn


class Reporter:
    def __init__(
        self,
        json_output: bool = False,
        quiet: bool = False,
        progress: bool = True,
        stderr: bool = False,
    ) -> None:
        self.json_output = json_output
        self.quiet = quiet
        self.progress_enabled = progress
        self.console = Console(stderr=stderr)

    def progress(self, description: str):
        if not self.progress_enabled or self.quiet:
            return _NullProgress()
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
        )

    def info(self, message: str) -> None:
        if self.quiet or self.json_output:
            return
        self.console.print(message)

    def emit_json(self, payload: Any) -> None:
        if self.quiet:
            return
        self.console.print(json.dumps(payload, indent=2, default=_json_default))


class _NullProgress:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def add_task(self, *args, **kwargs):
        return None

    def update(self, *args, **kwargs):
        return None

    def advance(self, *args, **kwargs):
        return None


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    try:
        return asdict(obj)
    except TypeError:
        return str(obj)

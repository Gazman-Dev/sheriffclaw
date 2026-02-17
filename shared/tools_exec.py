from __future__ import annotations

import json
import subprocess
from pathlib import Path


class ToolExecutor:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def exec(self, argv: list[str], stdin: str = "") -> dict:
        if not argv:
            raise ValueError("argv required")
        if any(tok in {"|", ";", "&&", "||"} for tok in argv):
            raise ValueError("shell tokens are not allowed")
        proc = subprocess.run(argv, input=stdin, text=True, capture_output=True, check=False)  # noqa: S603
        return {"code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}

    def save_output(self, run_id: str, result: dict) -> None:
        (self.output_dir / f"{run_id}.json").write_text(json.dumps(result), encoding="utf-8")

    def load_output(self, run_id: str) -> dict | None:
        p = self.output_dir / f"{run_id}.json"
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

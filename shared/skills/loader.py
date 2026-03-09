from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LoadedSkill:
    name: str
    description: str
    command: str
    tags: list[str]
    source: str
    root: Path


class SkillLoader:
    def __init__(self, user_root: Path, system_root: Path | None = None):
        self.user_root = user_root
        self.system_root = system_root

    def _discover_in_root(self, root: Path, source: str) -> dict[str, LoadedSkill]:
        out: dict[str, LoadedSkill] = {}
        if not root.exists():
            return out

        for skill_dir in root.iterdir():
            if not skill_dir.is_dir():
                continue
            manifest_path = skill_dir / "manifest.json"
            if not manifest_path.exists():
                continue

            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                name = raw.get("skill_id", skill_dir.name)
                out[name] = LoadedSkill(
                    name=name,
                    description=raw.get("description", ""),
                    command=raw.get("command", f"bash {skill_dir.name}/run.sh"),
                    tags=raw.get("tags", []),
                    source=source,
                    root=skill_dir,
                )
            except Exception:
                continue
        return out

    def load(self) -> dict[str, LoadedSkill]:
        skills: dict[str, LoadedSkill] = {}
        if self.system_root is not None:
            skills.update(self._discover_in_root(self.system_root, "system"))

        user_skills = self._discover_in_root(self.user_root, "user")
        for k, v in user_skills.items():
            if k not in skills:
                skills[k] = v
        return skills

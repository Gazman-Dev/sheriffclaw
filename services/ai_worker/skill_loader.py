from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


class SkillLoader:
    def __init__(self, root: Path):
        self.root = root
        self.skills: dict[str, ModuleType] = {}

    def load(self) -> dict[str, ModuleType]:
        self.skills.clear()
        if not self.root.exists():
            return self.skills
        for path in self.root.glob("*/skill.py"):
            spec = importlib.util.spec_from_file_location(f"skills.{path.parent.name}", path)
            if not spec or not spec.loader:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            name = getattr(mod, "SKILL_NAME", path.parent.name)
            self.skills[name] = mod
        return self.skills

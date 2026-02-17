from __future__ import annotations

import importlib.util
from pathlib import Path


class SkillLoader:
    def __init__(self, root: Path):
        self.root = root

    def load(self) -> dict[str, object]:
        skills: dict[str, object] = {}
        if not self.root.exists():
            return skills
        for skill_file in self.root.glob("*/skill.py"):
            mod_name = f"skills_{skill_file.parent.name}"
            spec = importlib.util.spec_from_file_location(mod_name, skill_file)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            name = getattr(module, "SKILL_NAME", skill_file.parent.name)
            skills[name] = module
        return skills

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LoadedSkill:
    name: str
    interface_module: object
    implementation_module: object
    source: str  # system|user
    root: Path


class SkillLoader:
    def __init__(self, user_root: Path, system_root: Path | None = None):
        self.user_root = user_root
        self.system_root = system_root

    @staticmethod
    def _load_module(mod_name: str, file_path: Path):
        spec = importlib.util.spec_from_file_location(mod_name, file_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _discover_in_root(self, root: Path, source: str) -> dict[str, LoadedSkill]:
        out: dict[str, LoadedSkill] = {}
        if not root.exists():
            return out

        for skill_dir in root.iterdir():
            if not skill_dir.is_dir():
                continue
            interface_py = skill_dir / "interface.py"
            impl_py = skill_dir / "implementation.py"
            legacy_py = skill_dir / "skill.py"

            if interface_py.exists() and impl_py.exists():
                interface_mod = self._load_module(f"skills_{source}_{skill_dir.name}_iface", interface_py)
                impl_mod = self._load_module(f"skills_{source}_{skill_dir.name}_impl", impl_py)
            elif source == "user" and legacy_py.exists():
                interface_mod = type("_LegacyInterface", (), {"SKILL_NAME": skill_dir.name})
                impl_mod = self._load_module(f"skills_{source}_{skill_dir.name}_legacy", legacy_py)
            else:
                continue
            if interface_mod is None or impl_mod is None:
                continue
            if not hasattr(impl_mod, "run"):
                continue

            name = getattr(interface_mod, "SKILL_NAME", getattr(impl_mod, "SKILL_NAME", skill_dir.name))
            out[name] = LoadedSkill(
                name=name,
                interface_module=interface_mod,
                implementation_module=impl_mod,
                source=source,
                root=skill_dir,
            )
        return out

    def load(self) -> dict[str, LoadedSkill]:
        skills: dict[str, LoadedSkill] = {}
        if self.system_root is not None:
            skills.update(self._discover_in_root(self.system_root, "system"))

        # user skills can override only if same name is not system
        user_skills = self._discover_in_root(self.user_root, "user")
        for k, v in user_skills.items():
            if k not in skills:
                skills[k] = v
        return skills

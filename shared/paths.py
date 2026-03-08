from __future__ import annotations

import os
import shutil
from pathlib import Path


def base_root() -> Path:
    root = os.environ.get("SHERIFFCLAW_ROOT")
    return Path(root).expanduser() if root else Path.home() / ".sheriffclaw"


def _ensure_island(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for child in ("run", "logs", "state"):
        (root / child).mkdir(parents=True, exist_ok=True)
    return root


def gw_root() -> Path:
    return _ensure_island(base_root() / "gw")


def llm_root() -> Path:
    return _ensure_island(base_root() / "llm")


def agent_root() -> Path:
    root = base_root() / "agents" / "codex"
    root.mkdir(parents=True, exist_ok=True)
    legacy_role_refs = {
        'config_file = ".codex/roles/subagent-medium.toml"': 'config_file = "roles/subagent-medium.toml"',
        'config_file = ".codex/roles/subagent-high.toml"': 'config_file = "roles/subagent-high.toml"',
    }

    def _copy_missing_tree(src: Path, dst: Path) -> None:
        for item in src.rglob("*"):
            rel = item.relative_to(src)
            rel_parts = rel.parts
            if len(rel_parts) >= 2 and rel_parts[0] == "conversations" and rel_parts[1] == "sessions":
                continue
            if rel_parts == (".codex", "config.toml"):
                target = dst / "config.toml"
            elif len(rel_parts) >= 2 and rel_parts[0] == ".codex" and rel_parts[1] == "roles":
                target = dst / Path(*rel_parts[1:])
            else:
                target = dst / rel
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)

    def _toml_basic_string(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _ensure_trusted_project(global_config: Path, workspace_root: Path) -> None:
        trust_header = f"[projects.{_toml_basic_string(str(workspace_root))}]"
        trust_line = 'trust_level = "trusted"'
        existing = global_config.read_text(encoding="utf-8") if global_config.exists() else ""
        if trust_header in existing and trust_line in existing:
            return
        with global_config.open("a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            if existing:
                fh.write("\n")
            fh.write(f"{trust_header}\n{trust_line}\n")

    def _rewrite_legacy_role_refs(config_path: Path) -> None:
        if not config_path.exists():
            return
        text = config_path.read_text(encoding="utf-8")
        updated = text
        for old, new in legacy_role_refs.items():
            updated = updated.replace(old, new)
        if updated != text:
            config_path.write_text(updated, encoding="utf-8")

    def _migrate_legacy_codex_config(dst: Path) -> None:
        legacy_config = dst / ".codex" / "config.toml"
        legacy_roles = dst / ".codex" / "roles"
        roles_dir = dst / "roles"
        global_config = dst / "config.toml"
        if legacy_config.exists() and not global_config.exists():
            legacy_config.replace(global_config)
        elif legacy_config.exists() and global_config.exists():
            legacy_text = legacy_config.read_text(encoding="utf-8")
            global_text = global_config.read_text(encoding="utf-8")
            if legacy_text == global_text:
                legacy_config.unlink()
            else:
                backup = dst / ".codex" / "config.toml.legacy"
                if not backup.exists():
                    legacy_config.replace(backup)
                else:
                    legacy_config.unlink()
        if legacy_roles.exists():
            roles_dir.mkdir(parents=True, exist_ok=True)
            for item in legacy_roles.rglob("*"):
                rel = item.relative_to(legacy_roles)
                target = roles_dir / rel
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)
        _rewrite_legacy_role_refs(global_config)
        _ensure_trusted_project(global_config, dst)

    source_candidates = [
        # Installer-managed source checkout location.
        base_root() / "source" / "agents" / "codex",
        # Developer checkout location.
        Path(__file__).resolve().parents[1] / "agents" / "codex",
    ]
    for src in source_candidates:
        if src.exists():
            _copy_missing_tree(src, root)
            break

    # Ensure minimal runtime folders always exist.
    for rel in (".codex", "conversations/sessions", "skill", "tmp", "roles"):
        (root / rel).mkdir(parents=True, exist_ok=True)

    _migrate_legacy_codex_config(root)

    return root

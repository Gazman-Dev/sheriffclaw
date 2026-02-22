from pathlib import Path

import pytest

from shared.skills.loader import SkillLoader
from shared.worker.worker_runtime import WorkerRuntime


def test_loader_prefers_system_skill(tmp_path):
    system = tmp_path / "system_skills" / "demo"
    user = tmp_path / "skills" / "demo"
    system.mkdir(parents=True)
    user.mkdir(parents=True)

    (system / "interface.py").write_text("SKILL_NAME='demo'\n", encoding="utf-8")
    (system / "implementation.py").write_text(
        "async def run(payload, emit_event=None, context=None):\n    return {'source':'system'}\n",
        encoding="utf-8",
    )
    (user / "interface.py").write_text("SKILL_NAME='demo'\n", encoding="utf-8")
    (user / "implementation.py").write_text(
        "async def run(payload, emit_event=None, context=None):\n    return {'source':'user'}\n",
        encoding="utf-8",
    )

    loader = SkillLoader(user_root=tmp_path / "skills", system_root=tmp_path / "system_skills")
    skills = loader.load()
    assert skills["demo"].source == "system"


def test_loader_legacy_skill_py_supported(tmp_path):
    user = tmp_path / "skills" / "legacy"
    user.mkdir(parents=True)
    (user / "skill.py").write_text(
        "SKILL_NAME='legacy'\nasync def run(payload, emit_event=None):\n    return {'ok':True}\n",
        encoding="utf-8",
    )
    loader = SkillLoader(user_root=tmp_path / "skills", system_root=tmp_path / "system_skills")
    skills = loader.load()
    assert "legacy" in skills


def test_sandboxed_path_blocks_escape(tmp_path):
    wr = WorkerRuntime()
    base = tmp_path / "w"
    base.mkdir(parents=True)
    ok = wr._sandboxed_path(base, "a/b.txt")
    assert str(ok).startswith(str(base.resolve()))

    with pytest.raises(ValueError):
        wr._sandboxed_path(base, "../../etc/passwd")

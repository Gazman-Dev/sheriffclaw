import json

import pytest

pytest.importorskip("hnswlib")

from shared.skills.loader import SkillLoader
from shared.worker.worker_runtime import WorkerRuntime


def test_loader_prefers_system_skill(tmp_path):
    system = tmp_path / "system_skills" / "demo"
    user = tmp_path / "skills" / "demo"
    system.mkdir(parents=True)
    user.mkdir(parents=True)

    (system / "manifest.json").write_text(json.dumps({"skill_id": "demo", "command": "sys"}), encoding="utf-8")
    (user / "manifest.json").write_text(json.dumps({"skill_id": "demo", "command": "usr"}), encoding="utf-8")

    loader = SkillLoader(user_root=tmp_path / "skills", system_root=tmp_path / "system_skills")
    skills = loader.load()

    assert "demo" in skills
    assert skills["demo"].source == "system"
    assert skills["demo"].command == "sys"


def test_sandboxed_path_blocks_escape(tmp_path):
    wr = WorkerRuntime()
    base = tmp_path / "w"
    base.mkdir(parents=True)
    ok = wr._sandboxed_path(base, "a/b.txt")
    assert str(ok).startswith(str(base.resolve()))

    with pytest.raises(ValueError):
        wr._sandboxed_path(base, "../../etc/passwd")

import json

from shared.skills.loader import SkillLoader


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

from pathlib import Path


def test_no_legacy_skill_py_files():
    root = Path("skills")
    for p in root.glob("*/skill.py"):
        raise AssertionError(f"legacy skill.py not allowed: {p}")
    for p in root.glob("*/interface.py"):
        # Emptied interfaces are allowed during migration, but ideally shouldn't exist.
        if "interface.py" in p.name and p.read_text().strip() and not p.read_text().startswith("#"):
            raise AssertionError(f"legacy interface.py not allowed in code-first paradigm: {p}")

def test_skills_have_manifests():
    root = Path("skills")
    for d in root.iterdir():
        if not d.is_dir():
            continue
        assert (d / "manifest.json").exists(), f"missing manifest.json in {d}"
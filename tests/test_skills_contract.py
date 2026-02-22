from pathlib import Path


def test_no_legacy_skill_py_files():
    root = Path("skills")
    for p in root.glob("*/skill.py"):
        raise AssertionError(f"legacy skill.py not allowed: {p}")


def test_python_skills_have_interface_and_implementation():
    root = Path("skills")
    for d in root.iterdir():
        if not d.is_dir():
            continue
        py_files = list(d.glob("*.py"))
        if not py_files:
            continue
        assert (d / "interface.py").exists(), f"missing interface.py in {d}"
        assert (d / "implementation.py").exists(), f"missing implementation.py in {d}"

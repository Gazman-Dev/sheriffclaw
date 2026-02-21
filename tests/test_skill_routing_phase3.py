from pathlib import Path

from shared.memory.skill_routing import SkillManifestLoader, route_skills


def test_skill_loader_loads_manifests():
    loader = SkillManifestLoader(Path("skills"))
    manifests = loader.load()
    ids = {m.skill_id for m in manifests}
    assert "write_docs" in ids
    assert "debug_trace" in ids


def test_route_docs_query_selects_write_docs():
    loader = SkillManifestLoader(Path("skills"))
    manifests = loader.load()
    selected, deep, reasons = route_skills("please write docs for this module", manifests)
    assert selected
    assert selected[0].skill_id == "write_docs"
    assert deep is True
    assert "docs" in reasons


def test_route_stack_trace_selects_debug_skill():
    loader = SkillManifestLoader(Path("skills"))
    manifests = loader.load()
    query = "Traceback (most recent call last): ValueError in parser.py same bug as before"
    selected, deep, reasons = route_skills(query, manifests)
    assert selected
    assert selected[0].skill_id == "debug_trace"
    assert deep is True
    assert "debug" in reasons

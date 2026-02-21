from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.memory.skill_routing import SkillManifestLoader, route_skills


def main() -> None:
    manifests = SkillManifestLoader(ROOT / "skills").load()

    docs_query = "please write docs for the installer and update the wiki"
    docs_selected, docs_deep, docs_reasons = route_skills(docs_query, manifests)
    print("DOCS_QUERY_SELECTED", docs_selected[0].skill_id if docs_selected else "none")
    print("DOCS_DEEP", docs_deep)
    print("DOCS_REASONS", ",".join(docs_reasons))

    debug_query = "Traceback (most recent call last): KeyError in service.py same bug"
    dbg_selected, dbg_deep, dbg_reasons = route_skills(debug_query, manifests)
    print("DEBUG_QUERY_SELECTED", dbg_selected[0].skill_id if dbg_selected else "none")
    print("DEBUG_DEEP", dbg_deep)
    print("DEBUG_REASONS", ",".join(dbg_reasons))


if __name__ == "__main__":
    main()

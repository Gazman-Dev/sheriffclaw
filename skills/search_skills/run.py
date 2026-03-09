#!/usr/bin/env python3
import sys
from pathlib import Path

# Add repo root to sys.path so we can import shared modules easily
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.skills.loader import SkillLoader


def lexical_score(query: str, text: str) -> float:
    q = [t for t in query.lower().split() if t]
    if not q:
        return 0.0
    low = text.lower()
    hits = sum(1 for t in q if t in low)
    return hits / len(q)


def main():
    query = " ".join(sys.argv[1:]).strip()
    if not query:
        print("Usage: python run.py <search_query>")
        sys.exit(1)

    loader = SkillLoader(user_root=ROOT / "skills", system_root=ROOT / "system_skills")
    skills = loader.load()

    results = []
    for name, skill in skills.items():
        if name == "search_skills":
            continue

        searchable = f"{skill.name} {skill.description} {' '.join(skill.tags)} {skill.command}"
        score = lexical_score(query, searchable)
        results.append((score, skill))

    results.sort(key=lambda x: x[0], reverse=True)

    print("--- Skill Search Results ---")
    found = False
    for score, skill in results[:5]:
        if score > 0:
            found = True
            print(f"Skill: {skill.name} (Score: {score:.2f})")
            print(f"Command: {skill.command}")
            print(f"Description: {skill.description}\n")

    if not found:
        print("No highly relevant skills found. Consider manually reading files in the skills/ directory.")


if __name__ == "__main__":
    main()

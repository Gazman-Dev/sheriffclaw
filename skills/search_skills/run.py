#!/usr/bin/env python3
import sys
import math
from pathlib import Path

# Add repo root to sys.path so we can import shared modules easily
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.skills.loader import SkillLoader
from shared.memory.embedding import LocalSemanticEmbeddingProvider

def cosine_similarity(v1, v2):
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)

def main():
    query = " ".join(sys.argv[1:]).strip()
    if not query:
        print("Usage: python run.py <search_query>")
        sys.exit(1)

    loader = SkillLoader(user_root=ROOT / "skills", system_root=ROOT / "system_skills")
    skills = loader.load()

    try:
        provider = LocalSemanticEmbeddingProvider()
    except RuntimeError as e:
        print(f"Error initializing embedding provider: {e}")
        sys.exit(1)

    query_vec = provider.embed(query)

    results =[]
    for name, skill in skills.items():
        if name == "search_skills":
            continue

        text_to_embed = f"{skill.description} {' '.join(skill.tags)}"
        if not text_to_embed.strip():
            text_to_embed = skill.name

        desc_vec = provider.embed(text_to_embed)
        score = cosine_similarity(query_vec, desc_vec)
        results.append((score, skill))

    results.sort(key=lambda x: x[0], reverse=True)

    print("--- Skill Search Results ---")
    found = False
    for score, skill in results[:5]:
        if score > 0.2:
            found = True
            print(f"Skill: {skill.name} (Score: {score:.2f})")
            print(f"Command: {skill.command}")
            print(f"Description: {skill.description}\n")

    if not found:
        print("No highly relevant skills found. Consider manually reading files in the skills/ directory.")

if __name__ == "__main__":
    main()
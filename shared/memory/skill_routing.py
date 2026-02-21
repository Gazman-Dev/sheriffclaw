from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SkillManifest:
    skill_id: str
    name: str
    description: str
    tags: list[str]
    requires_tools: list[str]
    default_reasoning_effort: str = "medium"


class SkillManifestLoader:
    def __init__(self, skills_root: Path):
        self.skills_root = skills_root

    def load(self) -> list[SkillManifest]:
        manifests: list[SkillManifest] = []
        if not self.skills_root.exists():
            return manifests

        for skill_dir in self.skills_root.iterdir():
            if not skill_dir.is_dir():
                continue
            manifest_path = skill_dir / "manifest.json"
            if manifest_path.exists():
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifests.append(
                    SkillManifest(
                        skill_id=raw.get("skill_id", skill_dir.name),
                        name=raw.get("name", skill_dir.name),
                        description=raw.get("description", ""),
                        tags=list(raw.get("tags", [])),
                        requires_tools=list(raw.get("requires_tools", [])),
                        default_reasoning_effort=raw.get("default_reasoning_effort", "medium"),
                    )
                )
            else:
                manifests.append(
                    SkillManifest(
                        skill_id=skill_dir.name,
                        name=skill_dir.name,
                        description="",
                        tags=[skill_dir.name],
                        requires_tools=[],
                        default_reasoning_effort="medium",
                    )
                )
        return manifests


LIGHT_SKILL_RULES = {
    "docs": ["doc", "docs", "documentation", "readme", "wiki"],
    "debug": ["error", "traceback", "stack trace", "exception", "bug", "failing"],
    "refactor": ["refactor", "rewrite", "restructure", "cleanup"],
    "tests": ["test", "tests", "pytest", "failing test"],
}

DEEP_SKILL_TRIGGERS = {
    "repo-edit": ["edit", "change", "modify", "update file", "across modules"],
    "tests": ["run tests", "failing test", "pytest"],
    "docs": ["write docs", "documentation", "wiki", "readme"],
    "debug": ["stack trace", "traceback", "same bug", "exception"],
    "multi-step": ["plan and implement", "step by step", "multi-step", "migrate"],
}


def _score_manifest(query: str, manifest: SkillManifest) -> float:
    q = query.lower()
    score = 0.0
    for tag in manifest.tags:
        if tag.lower() in q:
            score += 2.0
    if manifest.name.lower() in q:
        score += 2.0
    for token in manifest.description.lower().split():
        if token and token in q:
            score += 0.2
    return score


def _deep_trigger_reasons(query: str) -> list[str]:
    q = query.lower()
    reasons: list[str] = []
    for reason, terms in DEEP_SKILL_TRIGGERS.items():
        if any(t in q for t in terms):
            reasons.append(reason)
    return reasons


def search_skills(query: str, manifests: list[SkillManifest], k: int = 2) -> list[SkillManifest]:
    ranked = sorted(manifests, key=lambda m: _score_manifest(query, m), reverse=True)
    return [m for m in ranked if _score_manifest(query, m) > 0][:k]


def route_skills(query: str, manifests: list[SkillManifest]) -> tuple[list[SkillManifest], bool, list[str]]:
    # Light routing always
    light = search_skills(query, manifests, k=2)

    deep_reasons = _deep_trigger_reasons(query)
    deep = len(deep_reasons) > 0
    if not deep:
        return light[:2], False, []

    deep_ranked = search_skills(query, manifests, k=6)
    return deep_ranked, True, deep_reasons

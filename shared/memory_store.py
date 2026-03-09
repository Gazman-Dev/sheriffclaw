from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from shared import agent_repo


class MemoryStore:
    def __init__(self) -> None:
        agent_repo.ensure_layout()

    def append_inbox(
        self,
        *,
        session_key: str,
        text: str,
        channel: str,
        principal_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "ts": time.time(),
            "session_key": session_key,
            "channel": channel,
            "principal_id": principal_id,
            "text": text,
            "metadata": metadata or {},
        }
        self._append_jsonl(agent_repo.path_for("memory", "inbox.md"), entry)
        return entry

    def append_decision(
        self,
        *,
        session_key: str | None,
        text: str,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "ts": time.time(),
            "session_key": session_key,
            "source": source,
            "text": text,
            "metadata": metadata or {},
        }
        self._append_jsonl(agent_repo.path_for("memory", "decisions.md"), entry)
        return entry

    def replace_session_summary(self, session_key: str, summary_text: str) -> Path:
        path = agent_repo.summary_file(session_key)
        body = summary_text.rstrip() + "\n"
        path.write_text(body, encoding="utf-8")
        return path

    def append_session_note(self, session_key: str, note: str) -> Path:
        path = agent_repo.summary_file(session_key)
        existing = path.read_text(encoding="utf-8") if path.exists() else f"# Session Summary: {session_key}\n"
        if not existing.endswith("\n"):
            existing += "\n"
        existing += f"\n- {note.strip()}\n"
        path.write_text(existing, encoding="utf-8")
        return path

    def global_memory_snapshot(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for rel in (
            ("memory", "user_profile.md"),
            ("memory", "preferences.md"),
            ("memory", "global_facts.md"),
            ("memory", "ongoing_projects.md"),
            ("memory", "decisions.md"),
            ("memory", "inbox.md"),
            ("memory", "learned_patterns.md"),
            ("memory", "skill_candidates.md"),
        ):
            path = agent_repo.path_for(*rel)
            out["/".join(rel)] = path.read_text(encoding="utf-8")
        return out

    def recent_inbox_entries(self, *, session_key: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
        entries = self._read_jsonl_entries(agent_repo.path_for("memory", "inbox.md"))
        if session_key is not None:
            entries = [entry for entry in entries if entry.get("session_key") == session_key]
        return sorted(entries, key=lambda item: float(item.get("ts", 0)), reverse=True)[:limit]

    def recent_decisions(self, *, session_key: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
        entries = self._read_jsonl_entries(agent_repo.path_for("memory", "decisions.md"))
        if session_key is not None:
            entries = [entry for entry in entries if entry.get("session_key") == session_key]
        return sorted(entries, key=lambda item: float(item.get("ts", 0)), reverse=True)[:limit]

    def reconcile_session_summary(self, session_key: str, *, task_lines: list[str] | None = None) -> dict[str, Any]:
        recent_inbox = self.recent_inbox_entries(session_key=session_key, limit=6)
        recent_decisions = self.recent_decisions(session_key=session_key, limit=4)
        focus_line = recent_inbox[0]["text"] if recent_inbox else "No recent captured context."
        body = [
            f"# Session Summary: {session_key}",
            "",
            "## Current Focus",
            f"- {focus_line}",
            "",
            "## Active Tasks",
        ]
        body.extend(task_lines or ["- no tracked tasks"])
        body.extend(["", "## Recent Notes"])
        if recent_inbox:
            body.extend(f"- {entry['channel']}:{entry['principal_id']} -> {entry['text']}" for entry in recent_inbox)
        else:
            body.append("- no recent notes")
        body.extend(["", "## Recent Decisions"])
        if recent_decisions:
            body.extend(f"- {entry['text']}" for entry in recent_decisions)
        else:
            body.append("- no recorded decisions")
        path = self.replace_session_summary(session_key, "\n".join(body))
        return {"session_key": session_key, "summary_path": str(path), "notes": len(recent_inbox)}

    def reconcile_global_memory(
        self,
        *,
        task_lines: list[str],
        session_keys: list[str],
        decisions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        decision_entries = decisions if decisions is not None else self.recent_decisions(limit=8)
        recent_inbox = self.recent_inbox_entries(limit=24)

        ongoing_projects = ["# Ongoing Projects", "", "## Active Task Snapshot"]
        ongoing_projects.extend(task_lines or ["- no tracked tasks"])
        agent_repo.path_for("memory", "ongoing_projects.md").write_text(
            "\n".join(ongoing_projects).rstrip() + "\n",
            encoding="utf-8",
        )

        learned_patterns = ["# Learned Patterns", "", "## Recent Activity Patterns"]
        if recent_inbox:
            counts: dict[str, int] = {}
            for entry in recent_inbox:
                key = str(entry.get("session_key") or "unknown")
                counts[key] = counts.get(key, 0) + 1
            for session_key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]:
                learned_patterns.append(f"- {session_key} had {count} recent captured messages.")
        else:
            learned_patterns.append("- no recent activity captured")
        agent_repo.path_for("memory", "learned_patterns.md").write_text(
            "\n".join(learned_patterns).rstrip() + "\n",
            encoding="utf-8",
        )

        skill_candidates = ["# Skill Candidates", "", "## Maintenance Candidates"]
        if task_lines:
            skill_candidates.append("- Task reconciliation remains active; expand the task-manager skill.")
        if len(session_keys) > 1:
            skill_candidates.append("- Cross-session memory cleanup is recurring; expand the memory-manager skill.")
        if decision_entries:
            skill_candidates.append("- Decision consolidation is recurring; keep daily-update focused on durable promotion.")
        if len(skill_candidates) == 3:
            skill_candidates.append("- no strong skill candidates detected")
        agent_repo.path_for("memory", "skill_candidates.md").write_text(
            "\n".join(skill_candidates).rstrip() + "\n",
            encoding="utf-8",
        )

        return {
            "task_count": len(task_lines),
            "session_count": len(session_keys),
            "decision_count": len(decision_entries),
        }

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def _read_jsonl_entries(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            candidate = line.strip()
            if not candidate or not candidate.startswith("{"):
                continue
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                entries.append(payload)
        return entries

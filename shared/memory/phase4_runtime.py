from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from shared.memory.config import RetrievalConfig
from shared.memory.retrieval import render_topic_md, retrieve_topics
from shared.memory.runtime import sleep, wake
from shared.memory.skill_routing import SkillManifestLoader, route_skills


@dataclass
class Phase4RuntimeConfig:
    model: str = "gpt-5.2-codex"
    reasoning_effort: str = "medium"
    token_sleep_threshold: int = 12000
    max_tool_rounds: int = 8
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)


@dataclass
class RuntimeStores:
    topic_store: Any
    embedding_provider: Any
    semantic_index: Any
    wake_packet: dict | None
    skills_root: Any
    skill_runner: Callable[[str, dict], dict]
    repo_tools: dict[str, Callable[[dict], dict]]


class ModelAdapter:
    def create_response(self, request: dict) -> dict:
        raise NotImplementedError


class MockCodexAdapter(ModelAdapter):
    """Deterministic local adapter for tests/harness."""

    def create_response(self, request: dict) -> dict:
        user_text = ""
        for item in request.get("input", []):
            if item.get("role") == "user":
                chunks = item.get("content", [])
                if chunks:
                    user_text = chunks[0].get("text", "")

        # If tool results already present, finalize.
        has_tool_output = any(i.get("role") == "tool" for i in request.get("input", []))
        if has_tool_output:
            return {"type": "message", "content": "Done. Tool output received and applied."}

        low = user_text.lower()
        if "edit repo file" in low or "edit file" in low:
            return {
                "type": "tool_calls",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "name": "repo.write_file",
                        "arguments": {"path": "README.md", "content": "updated by tool"},
                    }
                ],
            }
        if "run skill" in low or "write docs" in low:
            return {
                "type": "tool_calls",
                "tool_calls": [
                    {
                        "id": "call-2",
                        "name": "skills.run",
                        "arguments": {"skill_id": "write_docs", "args": {"target": "README.md"}},
                    }
                ],
            }
        return {"type": "message", "content": "Acknowledged."}


def _now_iso(now: str | None) -> str:
    return now or datetime.now(timezone.utc).isoformat()


def _estimate_tokens(messages: list[dict]) -> int:
    # intentionally simple heuristic for phase 4
    chars = 0
    for m in messages:
        chars += len(str(m.get("content", "")))
    return max(1, chars // 4)


def _topic_tools(topic_store) -> dict[str, Callable[[dict], dict]]:
    def t_search(args: dict) -> dict:
        return {"topics": topic_store.search_by_alias(args.get("query", ""), k=int(args.get("k", 5)))}

    def t_get(args: dict) -> dict:
        ids = args.get("topic_ids", [])
        return {"topics": [topic_store.get(tid) for tid in ids if topic_store.get(tid)]}

    def t_upsert(args: dict) -> dict:
        t = topic_store.upsert_by_alias_overlap(
            name=args.get("name", "Topic"),
            one_liner=args.get("one_liner", ""),
            aliases=args.get("aliases", []),
            now_iso=_now_iso(None),
        )
        return {"topic_id": t.get("topic_id")}

    def t_link(args: dict) -> dict:
        topic_store.link_topics(
            from_topic_id=args.get("from_topic_id", ""),
            to_topic_id=args.get("to_topic_id", ""),
            edge_type=args.get("edge_type", "RELATES_TO"),
            weight=float(args.get("weight", args.get("weight_delta", 1.0))),
            now_iso=_now_iso(None),
            mode=args.get("mode", "add"),
        )
        return {"status": "linked"}

    return {
        "topics.search": t_search,
        "topics.get": t_get,
        "topics.upsert": t_upsert,
        "topics.link": t_link,
    }


def _memory_tools(stores: RuntimeStores):
    def m_sleep(args: dict) -> dict:
        return sleep(
            args.get("conversation_buffer", []),
            args.get("now"),
            stores.topic_store,
            keep_tail_turns=int(args.get("keep_tail_turns", 10)),
            embedding_provider=stores.embedding_provider,
            semantic_index=stores.semantic_index,
        )

    def m_wake(args: dict) -> dict:
        return wake(
            args.get("wake_packet", {}),
            args.get("user_msg", ""),
            args.get("now"),
            stores.topic_store,
        )

    return {
        "memory.sleep": m_sleep,
        "memory.wake": m_wake,
    }


def _skill_tools(stores: RuntimeStores):
    def s_search(args: dict) -> dict:
        manifests = SkillManifestLoader(stores.skills_root).load()
        selected, deep, reasons = route_skills(args.get("query", ""), manifests)
        return {
            "skills": [
                {
                    "skill_id": s.skill_id,
                    "name": s.name,
                    "description": s.description,
                    "tags": s.tags,
                }
                for s in selected
            ],
            "deep": deep,
            "reasons": reasons,
        }

    def s_run(args: dict) -> dict:
        return stores.skill_runner(args.get("skill_id", ""), args.get("args", {}))

    return {
        "skills.search": s_search,
        "skills.run": s_run,
    }


def _tool_schemas() -> list[dict]:
    return [
        {"type": "function", "name": "topics.search", "description": "Search topics", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer"}}, "required": ["query"]}},
        {"type": "function", "name": "topics.get", "description": "Get topics by ids", "parameters": {"type": "object", "properties": {"topic_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["topic_ids"]}},
        {"type": "function", "name": "topics.upsert", "description": "Upsert topic", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "one_liner": {"type": "string"}, "aliases": {"type": "array", "items": {"type": "string"}}}, "required": ["name", "aliases"]}},
        {"type": "function", "name": "topics.link", "description": "Link two topics", "parameters": {"type": "object", "properties": {"from_topic_id": {"type": "string"}, "to_topic_id": {"type": "string"}, "edge_type": {"type": "string", "enum": ["RELATES_TO", "DEPENDS_ON", "PART_OF"]}, "weight": {"type": "number"}, "mode": {"type": "string", "enum": ["set", "add"]}}, "required": ["from_topic_id", "to_topic_id"]}},
        {"type": "function", "name": "memory.sleep", "description": "Compact memory", "parameters": {"type": "object", "properties": {"conversation_buffer": {"type": "array"}, "now": {"type": "string"}, "keep_tail_turns": {"type": "integer"}}, "required": ["conversation_buffer"]}},
        {"type": "function", "name": "memory.wake", "description": "Wake and retrieve", "parameters": {"type": "object", "properties": {"wake_packet": {"type": "object"}, "user_msg": {"type": "string"}, "now": {"type": "string"}}, "required": ["wake_packet", "user_msg"]}},
        {"type": "function", "name": "skills.search", "description": "Search skills", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
        {"type": "function", "name": "skills.run", "description": "Run skill", "parameters": {"type": "object", "properties": {"skill_id": {"type": "string"}, "args": {"type": "object"}}, "required": ["skill_id"]}},
        {"type": "function", "name": "repo.list_files", "description": "List repo files", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}}},
        {"type": "function", "name": "repo.read_file", "description": "Read file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        {"type": "function", "name": "repo.write_file", "description": "Write file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
        {"type": "function", "name": "repo.run_tests", "description": "Run tests", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}},
    ]


def _to_input_message(role: str, text: str) -> dict:
    return {"role": role, "content": [{"type": "input_text", "text": text}]}


def _make_request(model: str, reasoning_effort: str, system_prompt: str, messages: list[dict], tool_schemas: list[dict]) -> dict:
    return {
        "model": model,
        "input": [_to_input_message("system", system_prompt), *messages],
        "tools": tool_schemas,
        "reasoning": {"effort": reasoning_effort},
    }


def run_turn(
        conversation_buffer: list[dict],
        user_msg: str,
        now: str,
        stores: RuntimeStores,
        config: Phase4RuntimeConfig,
        model_adapter: ModelAdapter,
) -> dict:
    logs: dict[str, Any] = {"events": []}
    now_iso = _now_iso(now)

    working_buffer = list(conversation_buffer)
    working_buffer.append({"role": "user", "content": user_msg})

    maybe_wake_packet = stores.wake_packet
    if _estimate_tokens(working_buffer) > config.token_sleep_threshold:
        slept = sleep(
            conversation_buffer=working_buffer,
            now=now_iso,
            topic_store=stores.topic_store,
            keep_tail_turns=10,
            embedding_provider=stores.embedding_provider,
            semantic_index=stores.semantic_index
        )
        maybe_wake_packet = slept["wake_packet"]
        working_buffer = slept["trimmed_conversation"]
        logs["events"].append({"type": "sleep", "topics_updated": slept["topics_updated"]})
        wake_info = wake(maybe_wake_packet, user_msg, now_iso, stores.topic_store)
        logs["events"].append({"type": "wake", "retrieved_count": len(wake_info.get("retrieved_topics", []))})

    retrieval = retrieve_topics(
        query=user_msg,
        now_iso=now_iso,
        wake_packet=maybe_wake_packet,
        topic_store=stores.topic_store,
        embedding_provider=stores.embedding_provider,
        semantic_index=stores.semantic_index,
        config=config.retrieval,
    )
    logs["retrieved_topic_ids"] = [t.get("topic_id") for t in retrieval.topics]

    manifests = SkillManifestLoader(stores.skills_root).load()
    skill_selected, skill_deep, skill_reasons = route_skills(user_msg, manifests)
    logs["retrieved_skills"] = [s.skill_id for s in skill_selected]
    logs["skill_deep"] = skill_deep
    logs["skill_reasons"] = skill_reasons

    topic_md = "\n\n".join(render_topic_md(t) for t in retrieval.topics[:8])
    skill_md = "\n".join(f"- {s.skill_id}: {s.description}" for s in skill_selected)
    system_prompt = (
        "You are SheriffClaw runtime assistant. Use tools when needed.\n"
        f"Retrieved topics:\n{topic_md or '(none)'}\n"
        f"Retrieved skills:\n{skill_md or '(none)'}"
    )

    tool_handlers: dict[str, Callable[[dict], dict]] = {}
    tool_handlers.update(_topic_tools(stores.topic_store))
    tool_handlers.update(_memory_tools(stores))
    tool_handlers.update(_skill_tools(stores))
    tool_handlers.update(stores.repo_tools)

    tool_schemas = _tool_schemas()

    req_messages = [_to_input_message("user", user_msg)]

    assistant_msg = ""
    for _ in range(config.max_tool_rounds):
        request = _make_request(config.model, config.reasoning_effort, system_prompt, req_messages, tool_schemas)
        logs["last_request"] = request
        resp = model_adapter.create_response(request)

        if resp.get("type") == "message":
            assistant_msg = resp.get("content", "")
            break

        if resp.get("type") == "tool_calls":
            for tc in resp.get("tool_calls", []):
                name = tc.get("name")
                args = tc.get("arguments", {})
                handler = tool_handlers.get(name)
                result = {"error": f"unknown tool: {name}"} if handler is None else handler(args)
                logs["events"].append({"type": "tool_call", "name": name, "args": args})
                req_messages.append(
                    {
                        "role": "tool",
                        "content": [
                            {
                                "type": "input_text",
                                "text": json.dumps({"tool_name": name, "result": result}, ensure_ascii=False),
                            }
                        ],
                    }
                )
            continue

        assistant_msg = "No response"
        break

    updated_buffer = working_buffer + [{"role": "assistant", "content": assistant_msg}]
    return {
        "assistant_msg": assistant_msg,
        "updated_buffer": updated_buffer,
        "maybe_wake_packet": maybe_wake_packet,
        "logs": logs,
    }
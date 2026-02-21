# Task: Sheriff Claw Memory Architecture Refactor (Codex-first)

Source: user specification message (saved verbatim)

---
# Sheriff Claw Memory Architecture Tech Spec (Codex-first)
## 0) Goals
### Product goals
1. One continuous conversation (single chat stream UX).
2. Always-on relevance: every assistant turn can opportunistically recall 1–N helpful topic memories and 0–N skills without the user asking.
3. Sleep/Wake as a core mechanic:
* Sleep happens when context budget is tight (or policy triggers).
* Sleep compacts conversation into durable topic memory.
* Wake restores minimal context and resumes work if mid-task.
4. Sense of time:
* “last week / yesterday / before you slept” resolves to real windows.
* Topics maintain first/last touched timestamps and notable events.
5. Codex-first implementation:
* Use Responses API for all model calls and tool calling. ([OpenAI Platform][1])
* Use GPT-5.2-Codex (or GPT-5.1-Codex) for agentic coding tasks. ([OpenAI Developers][2])
* Implement memory + skills as host-side tools callable by the model (function calling). ([OpenAI Developers][3])
### Non-goals
* No separate “user profile” memory type. Everything is stored as topics (including preferences if they become important).
* No user-visible “threads.” We may compute “subjects” internally, but never expose as a concept.
---
## 1) Core Concepts (match your list)
### 1.1 Topics (persistent)
Durable memory artifacts. Stored as structured records, searchable by:
* aliases (lexical)
* embeddings (semantic)
* time constraints
### 1.2 Subjects (ephemeral)
Internal, short-lived clustering of “what’s happening in the recent span.” Used only during sleep/wake/ranking.
Not persisted as a primary memory object (can be logged for debugging).
### 1.3 Skills (code)
Each skill is Python code with a manifest + docs.
Skills orchestrate tools and optionally produce code/doc artifacts.
Skills can be retrieved like topics and/or invoked as tools.
### 1.4 Tools (executors)
Host-provided functions callable by the model: retrieve topics, upsert topics, run a skill, read/write repo files, run tests, etc.
Built using OpenAI function calling. ([OpenAI Developers][3])
### 1.5 Time (first-class signal)
Every message, topic update, tool call, and sleep/wake event is timestamped (UTC + local optional).
Relative time phrases are resolved at runtime.
### 1.6 Sleep & Wake (pipelines)
* Sleep: compact chat → update topics graph/index → produce wake packet.
* Wake: load wake packet + retrieve relevant topics/skills → resume.
---
## 2) Storage Model
### 2.1 Topic record schema
Use a versioned schema (JSON). Recommended fields:
{
"schema_version": 1,
"topic_id": "uuid",
"name": "Sheriff Claw memory architecture",
"one_liner": "We are implementing Sheriff Claw memory using topics, sleep/wake, time, and skill scripts.",
"facts": ["..."],
"numbers": [
{"key":"context_window_tokens","value":400000,"unit":"tokens","at":"2026-02-20T03:21:00Z","source":"doc|user|tool","confidence":0.8}
],
"open_loops": ["..."],
"aliases": ["sheriff claw memory", "sleep pipeline", "topic compaction"],
"time": {
"first_seen_at": "2026-02-20T03:21:00Z",
"last_seen_at": "2026-02-20T03:55:00Z",
"notable_events": [
{"at":"2026-02-20T03:55:00Z","event":"Defined triggers for topic+skill retrieval"}
]
},
"links": {
"related_topic_ids": ["uuid2","uuid3"],
"skill_refs": ["skill:write_docs","skill:repo_refactor"],
"artifact_refs": ["repo:path/to/doc.md"]
},
"embedding": {
"model": "text-embedding-3-large|etc",
"vector": [/* stored externally if needed */],
"hash": "..."
},
"stats": {
"utility_score": 12.3,
"decay_bucket": "warm",
"touch_count": 9
}
}
Notes
* one_liner is the canonical semantic key (vectorized).
* facts/open_loops/numbers are structured, not prose.
* utility_score drives what gets loaded after wake.
### 2.2 Topic graph (optional but recommended)Maintain edge table:
{
"from_topic_id": "uuidA",
"to_topic_id": "uuidB",
"type": "RELATES_TO|DEPENDS_ON|PART_OF|NEXT|PREV",
"weight": 0.0,
"last_updated_at": "..."
}
Graph is used only for expansion after initial retrieval.
### 2.3 Wake packet schema
Tiny state written at sleep completion:
{
"schema_version": 1,
"slept_at": "2026-02-20T04:00:00Z",
"conversation_tail": [
{"role":"user","content":"..."},
{"role":"assistant","content":"..."}
],
"active_subject_hints": ["memory architecture","codex integration"],
"top_topic_ids": ["uuid1","uuid7","uuid3"],
"recent_skill_refs": ["skill:plan_and_execute","skill:write_docs"],
"in_progress": {
"status": "idle|running|blocked",
"resume_hint": "Continue implementing sleep pipeline in memory.py",
"topic_id": "uuid1"
}
}
---
## 3) Skill System (Codex-friendly)
### 3.1 Skill packaging
Each skill is a Python module folder:
skills/
write_docs/
manifest.json
skill.py
README.md
tests/
repo_refactor/
...
### 3.2 Skill manifest schema
{
"skill_id": "write_docs",
"name": "Write documentation",
"description": "Generates or updates docs in repo using project conventions.",
"inputs_schema": {...},
"outputs_schema": {...},
"requires_tools": ["repo.read_file","repo.write_file"],
"default_reasoning_effort": "medium",
"tags": ["docs","repo"],
"examples": [...]
}
### 3.3 Invocation model
Skills can be:
* retrieved (to inform the model how to proceed), and/or
* executed as a tool call:
skills.run(skill_id, args).
This aligns with OpenAI tool calling flow (model chooses a tool, host executes, host returns tool output, model continues). ([OpenAI Developers][3])
---
## 4) Runtime Pipelines
## 4.1 Awake loop (per user message)
Inputs
* full chat log (or tail) + wake packet (if present)
* current time (UTC)
* topic store + indexes
* skills registry
Steps
1. Light topic retrieval (always-on)
* Query = user message + short recent tail
* Retrieve top K candidates (e.g., K=5–8) from embeddings + alias match.
2. Light skill routing (always-on)
* classify intent: “coding / docs / debug / planning / memory reference”
* retrieve top 0–2 skills (manifest only).
3. Trigger deep retrieval (conditional)
* run deep topic retrieval if any trigger hit (see §5).
* run deep skill retrieval if task needs orchestration/tooling.
4. Compose model input
* System prompt (Sheriff Claw behavior, sleep/wake policy)
* Conversation tail (short)
* Retrieved topic snippets (structured, compact)
* Retrieved skill manifests/templates (compact)
* Tools list (topic store tools, skill runner, repo tools, etc.)
5. Call Codex model via Responses API
* model = gpt-5.2-codex preferred for long-horizon coding. ([OpenAI Developers][2])
6. Handle tool calls
* Execute host tool(s), return outputs, continue until final assistant message.
Model notes
* Codex models are available via Responses API (and designed for agentic coding). ([OpenAI Developers][4])
---
## 4.2 Sleep pipeline (compaction)
Trigger conditions
* context budget nearing limit
* explicit “sleep now”
* periodic maintenance (optional)
Inputs
* full conversation buffer
* last sleep marker / wake packet
* time now
Steps
1. Select compaction slice
* Keep last T turns verbatim as “tail” (e.g., 10–30 turns).
* Compact everything before tail.
2. Compute subjects over compacted slice
* Output 1–N subject hints + salience scores
* Subject hints are internal only.
3. Extract topic updates
* Identify candidate topics from slice:
* noun phrases, project names, decisions, constraints, “do you remember X”
* repeated instructions (formatting prefs, tooling prefs)
* mid-task state if present
4. Topic matching
For each candidate:
* alias match (strong)
* embedding similarity on one_liner (strong)
* time proximity when time phrases appear
* if match score ≥ threshold → merge; else create new.
5. Normalize into topic structure* Update one_liner minimally (avoid drift)
* Append/merge facts, open_loops
* Write numbers as typed entries (never bury in prose)
* Update aliases based on how the user referred to it
* Update time.last_seen_at, add notable events
6. Graph edge updates (if graph enabled)
* Co-activation in same slice → increase RELATES_TO
* Detected dependency language → add DEPENDS_ON
* Optional NEXT/PREV based on temporal adjacency
7. Utility scoring + decay
* Increase utility if: corrected by user, used to complete a task, referenced frequently, impacts output constraints.
* Decay old topics by time since last_seen.
8. Write wake packet
* include slept_at, conversation tail, top topic ids by (utility × recency × subject salience)
* include recent skills used
* include in_progress resume hint (if any)
9. Trim conversation buffer
* drop compacted slice; keep tail + wake packet reference
---
## 4.3 Wake pipeline
Inputs
* wake packet
* new user message (or continue if sleep occurred mid-generation)
Steps
1. Load conversation tail and slept_at.
2. Determine whether to resume:
* If in_progress.status == running and time since slept_at is “fresh” (config), resume automatically.
* If stale, ask for confirmation OR re-plan.
3. Run light topic retrieval using:
* user message + resume hint + subject hints
4. Optional deep retrieval:
* time phrases (“last week”, “before sleep”) trigger time-window filtering + graph expansion.
5. Load recent skill refs (2–5) into context as manifests/templates.
6. Call Codex model to proceed.
---
# 5) Retrieval Triggers (always-search + deep-search)
You want “always searching,” so implement two modes:
## 5.1 Light search (always, every user message)
* Topics: retrieve K=5–8 candidates
* Skills: retrieve K=0–2 manifests
## 5.2 Deep search triggers (topics)
Deep topics retrieval (K=12–25 + graph expand 1 hop) if any:
1. Memory reference language: “remember”, “last time”, “we spoke about”
2. Relative time phrases: “last week”, “yesterday”, “before you slept”
3. Reintroduced entity not in tail: module name, feature codename, person, event label
4. Low-confidence routing: top topic scores are close or low
5. Hard context switch markers: “anyway”, “new thing”, “separately”
6. Debug recurrence: stack traces / “same failure as before”
## 5.3 Deep search triggers (skills)
Deep skill retrieval (K=3–6, include templates + helper docs) if any:
1. User asks to change repo/code/docs/tests
2. Multi-step request (“implement across modules”, “refactor”, “migrate”)
3. Prior attempt failed (last tool output indicates error)
4. Planning request (“how should we architect…”, “design spec”)
---
# 6) Time: Requirements & Implementation
## 6.1 Time normalization
* Store all internal timestamps as UTC ISO-8601.
* When parsing phrases:
* “last week” → [now-7d, now] (or week boundary rules if desired)
* “yesterday” → previous day window
* “before sleep” → [*, slept_at]
## 6.2 Time-aware ranking
When user includes time phrase:
* Filter candidate topics by last_seen_at proximity to window
* Boost topics with notable events inside the window
## 6.3 Topic events (optional but strong)
If you want more narrative recall, store TopicEvent records on each sleep update:
* (topic_id, at, delta_summary, turn_range)
This improves answers like “what did we decide last week?”
---
# 7) Codex / Responses API Integration
## 7.1 Model selection
* Primary: gpt-5.2-codex for complex repo tasks, long horizon coding. ([OpenAI Developers][2])
* Alternative: gpt-5.1-codex where appropriate. ([OpenAI Developers][4])
Both are used via the Responses API. ([OpenAI Platform][1])
## 7.2 Tool calling contract
Implement tools using OpenAI function calling:
* Provide tools[] in the Responses request
* Model emits tool calls with JSON args
* Host executes and returns tool outputs
* Model continues until final response ([OpenAI Developers][3])
## 7.3 Recommended host tools (minimum)
### Topic tools* topics.search(query, time_window?, k, filters?) -> [TopicSnippet]
* topics.get(topic_ids) -> [TopicFull]
* topics.upsert(topic_update) -> {topic_id}
* topics.link(from, to, type, weight_delta)
### Sleep/Wake tools
* memory.sleep(conversation_buffer, now) -> WakePacket
* memory.wake(wake_packet, user_msg, now) -> {topics, skills, resume_plan}
### Skill tools
* skills.search(query, k) -> [SkillManifest]
* skills.run(skill_id, args, ctx_refs) -> SkillResult
### Repo tools (Codex workflow)
* repo.list_files(pattern?)
* repo.read_file(path)
* repo.write_file(path, content)
* repo.run_tests(command|preset)
(Exact repo tool set depends on Sheriff repo setup.)
## 7.4 Reasoning effort dial (Codex)
Codex supports reasoning effort settings; use higher effort for sleep compaction + complex refactors, lower for quick edits. ([OpenAI Developers][2])
---
# 8) Ranking & Scoring (practical defaults)
## 8.1 Topic match score (for merge vs create)
Weighted sum:
* alias match: +3.0
* embedding similarity: +0..3.0
* entity overlap: +0..1.5
* time proximity if time hint: +0..2.0
Threshold:
* ≥ 4.0 merge
* else create new topic
## 8.2 Retrieval score (for loading into context)
score = relevance * (1 + utility_boost) * recency_boost * time_window_boost
Where:
* relevance = embedding sim + alias
* utility_boost derived from touch_count, correction_count, “constraint” markers
* recency_boost = exp(-(now - last_seen)/tau)
* time_window_boost = strong if within requested window
## 8.3 Utility updates (during sleep)
Add:
* +5 if user corrected assistant about topic
* +3 if topic directly constrained output format or behavior
* +2 if topic used in successful skill completion
* +1 per mention in the slice
Decay:
* multiply by 0.98 per day since last seen (tunable)
---
# 9) Observability & Debugging (strongly recommended)
If using OpenAI Agents SDK, enable tracing to debug tool calls and long workflows. ([OpenAI Developers][5])
Minimum logging (even without SDK):
* each Responses call: input size, retrieved topics/skills ids
* each tool call: name, args hash, duration, success/failure
* sleep runs: topics created/updated count, wake packet size
* retrieval: top candidates and scores (for tuning)
---
# 10) Acceptance Tests (must-have)
1. Always-on recall
* Given a new user message referencing a previous concept (“party”), system retrieves correct topic without explicit “search” instruction.
2. Time resolution
* “last week” pulls topics last_seen in that window; “before sleep” uses slept_at.
3. Sleep compaction
* After sleep, conversation buffer shrinks; topics updated; wake packet created.
4. Mid-task resume
* If sleep occurs mid-task, wake resumes with correct goal and next step.
5. Skill routing
* “write docs” triggers docs skill; “refactor module” triggers refactor skill; debugging triggers debug skill.
6. Merge correctness
* Repeated mentions of same concept merge into one topic; different parties at different times produce separate topics (time anchors prevent overwrite).
---
## 11) Implementation Checklist for the AI with Repo Access
1. Add memory/ module:
* topic store interface
* embedding index + alias index
* optional graph edges
* sleep/wake functions
2. Add skills/ framework:
* manifest loader
* search (tags + embeddings on description)
* runner with ctx
3. Add tools/ layer for function calling:
* implement topic tools, sleep/wake tools, skills tools, repo tools
4. Integrate with Responses API:
* request builder includes conversation tail + retrieved topic snippets + skill manifests
* tool calling loop per OpenAI docs ([OpenAI Developers][3])
5. Add tests and a small “simulated conversation” harness to validate sleep/wake and retrieval scoring.
---
[1]: https://platform.openai.com/docs/api-reference/responses?utm_source=chatgpt.com "Responses | OpenAI API Reference"
[2]: https://developers.openai.com/api/docs/models/gpt-5.2-codex?utm_source=chatgpt.com "GPT-5.2-Codex Model | OpenAI API"
[3]: https://developers.openai.com/api/docs/guides/function-calling/?utm_source=chatgpt.com "Function calling | OpenAI API"
[4]: https://developers.openai.com/api/docs/models/gpt-5.1-codex?utm_source=chatgpt.com "GPT-5.1 Codex Model | OpenAI API"
[5]: https://developers.openai.com/api/docs/guides/agents-sdk/?utm_source=chatgpt.com "Agents SDK | OpenAI API"

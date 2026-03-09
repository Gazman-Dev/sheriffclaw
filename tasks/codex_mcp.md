# Spec: Using Codex CLI as `codex mcp-server` for a Persistent Telegram Agent

## 1. Goal

Use **Codex CLI running as an MCP server** as the engine behind the Telegram agent, so the integration can:

* keep Codex alive across multiple turns to avoid repeated cold starts,
* route messages into long-lived Codex conversations,
* preserve application state in a repo,
* support:

    * **private chat** → one main session,
    * **group chat** → one session per topic. ([OpenAI Developers][2])

This spec is intentionally strict about official behavior:

* `codex mcp-server` is officially documented as an **experimental** command that runs Codex as an MCP server over **stdio**. It inherits normal global Codex configuration overrides and exits when the downstream client closes the connection. ([OpenAI Developers][1])
* The documented MCP surface exposes **two tools only**:

    * `codex`
    * `codex-reply` ([OpenAI Developers][2])

---

## 2. Critical design decision

### 2.1 Recommended runtime model

Run **one long-lived `codex mcp-server` process** inside your agent service and keep the MCP connection open for as long as the service is running. That is the official way to avoid repeated startup overhead, because the documented MCP mode “keeps Codex alive across multiple agent turns.” ([OpenAI Developers][2])

### 2.2 Session identity model

Use **your own application-level session keys** and map them to Codex MCP `threadId`s:

* private chat → `private_main`
* group topic → `group_<chat_id>_topic_<topic_id>`

Store this mapping in your repo metadata.

Reason: in the official MCP docs, the `codex` tool starts a conversation and returns a `threadId`, while `codex-reply` requires that returned `threadId` to continue. The documented `codex` input does **not** include a `threadId` field, so there is no documented way to choose your own thread ID at thread creation time. The safe conclusion is: **you choose your own app session key, Codex chooses the MCP thread ID, and you persist the mapping.** ([OpenAI Developers][2])

---

## 3. Hard limitation to understand up front

## 3.1 What is officially documented

The official MCP-server docs say:

* start the server with `codex mcp-server`,
* use `codex` to start a conversation,
* use `codex-reply` with the returned `threadId` to continue it,
* keep the server process alive across turns. ([OpenAI Developers][2])

## 3.2 What is **not** officially documented

The official MCP-server docs do **not** document a supported mechanism to:

* resume an MCP `threadId` after a **server restart**,
* enumerate existing MCP threads from a previous server process,
* supply a custom caller-chosen `threadId` to the `codex` tool. ([OpenAI Developers][2])

## 3.3 Practical implication

You should treat MCP `threadId`s as **process-lifetime conversation handles** unless and until OpenAI documents restart persistence for them.

So the correct implementation strategy is:

* while the service stays up:

    * keep the MCP server alive,
    * keep using the same `threadId` for that topic/chat.
* after service restart:

    * assume prior MCP `threadId`s may no longer be resumable,
    * create a **new** MCP thread,
    * hydrate it from repo-backed summaries, tasks, and memory.

That is the safest implementation consistent with the official docs. The docs do document durable local session resume for **CLI sessions** via `codex resume` / `codex exec resume`, and they document resumable threads for **app-server**, but not for `codex mcp-server`. ([OpenAI Developers][1])

---

## 4. Official CLI command surface relevant to this design

## 4.1 Start Codex as an MCP server

Official command:

```bash
codex mcp-server
```

The official docs also show launching it through the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector codex mcp-server
```

`codex mcp-server` is documented as experimental, stdio-based, and inherited from the normal Codex config/global override system. ([OpenAI Developers][2])

## 4.2 Global flags that apply to `codex mcp-server`

The CLI reference says global flags apply to the base `codex` command and propagate to subcommands unless a section says otherwise. The documented global flags include: `--add-dir`, `--ask-for-approval/-a`, `--cd/-C`, `--config/-c`, `--dangerously-bypass-approvals-and-sandbox/--yolo`, `--disable`, `--enable`, `--full-auto`, `--image/-i`, `--model/-m`, `--no-alt-screen`, `--oss`, `--profile/-p`, `--sandbox/-s`, and `--search`. There are **no command-specific flags documented for `codex mcp-server` itself** beyond those inherited global flags. ([OpenAI Developers][1])

For this project, the most relevant ones are:

* `--cd/-C <path>` — set working directory
* `--model/-m <string>` — override model
* `--profile/-p <string>` — load a named profile from config
* `--sandbox/-s <read-only|workspace-write|danger-full-access>`
* `--ask-for-approval/-a <untrusted|on-request|never>`
* `--add-dir <path>` — additional writable roots
* `--config/-c key=value` — inline config override
* `--search` — turn on live web search if needed. ([OpenAI Developers][1])

---

## 5. Official MCP API exposed by `codex mcp-server`

When a client connects and calls `tools/list`, the official docs say there are **two tools**. ([OpenAI Developers][2])

## 5.1 Tool: `codex`

Purpose: start a new Codex conversation. ([OpenAI Developers][2])

Official documented input properties:

```json
{
  "prompt": "string, required",
  "approval-policy": "string, optional",
  "base-instructions": "string, optional",
  "config": "object, optional",
  "cwd": "string, optional",
  "include-plan-tool": "boolean, optional",
  "model": "string, optional",
  "profile": "string, optional",
  "sandbox": "string, optional"
}
```

Official meanings:

* `prompt` — initial user prompt
* `approval-policy` — `untrusted`, `on-request`, or `never`
* `base-instructions` — replaces default instructions
* `config` — configuration overrides matching Codex `Config`
* `cwd` — working directory
* `include-plan-tool` — whether to include the plan tool
* `model` — model override
* `profile` — named config profile
* `sandbox` — `read-only`, `workspace-write`, or `danger-full-access`. ([OpenAI Developers][2])

## 5.2 Tool: `codex-reply`

Purpose: continue an existing Codex conversation. ([OpenAI Developers][2])

Official documented input properties:

```json
{
  "prompt": "string, required",
  "threadId": "string, required",
  "conversationId": "string, optional, deprecated"
}
```

Official meanings:

* `prompt` — next user message
* `threadId` — thread to continue
* `conversationId` — deprecated alias for `threadId`. ([OpenAI Developers][2])

## 5.3 Response shape

The docs show that tool responses include `structuredContent`, and for compatibility may also include `content`. The important field is:

```json
{
  "structuredContent": {
    "threadId": "019bbb20-bff6-7130-83aa-bf45ab33250e",
    "content": "..."
  }
}
```

The docs explicitly say to use `structuredContent.threadId` from the `tools/call` response, and approval prompts also include `threadId` in their `params` payload. ([OpenAI Developers][2])

---

## 6. Official config keys most relevant to this project

The full Config surface is large, but for your design these are the most relevant documented keys.

### 6.1 History persistence

Codex config includes:

* `history.persistence = "save-all" | "none"`
* `history.max_bytes = <number>`

`history.persistence` controls whether Codex saves session transcripts to `history.jsonl`. `history.max_bytes` caps history file size by dropping oldest entries. ([OpenAI Developers][3])

### 6.2 Model and instructions

Relevant documented keys include:

* `model`
* `model_auto_compact_token_limit`
* `model_context_window`
* `model_instructions_file`
* `profile`
* `profiles.<name>.*` overrides. ([OpenAI Developers][3])

Important details:

* `model` sets the model, for example `gpt-5-codex`
* `model_instructions_file` replaces built-in instructions instead of `AGENTS.md`
* `profiles.<name>.*` can override supported config keys for a named profile. ([OpenAI Developers][3])

### 6.3 Sandbox

Relevant documented keys include:

* `sandbox_mode = "read-only" | "workspace-write" | "danger-full-access"`
* `sandbox_workspace_write.network_access`
* `sandbox_workspace_write.writable_roots` and related workspace-write options. ([OpenAI Developers][3])

### 6.4 Notifications

`notify` is a documented config key: a command invoked for notifications, receiving a JSON payload from Codex. That can be useful later if you want local hooks, though it is not required for the Telegram runtime. ([OpenAI Developers][3])

---

## 7. Official CLI resume/fork behavior, and why it matters here

The official CLI docs document persistent local sessions for interactive and exec workflows:

* `codex resume`
* `codex exec resume`
* `codex fork` ([OpenAI Developers][1])

Key official facts:

* `codex resume <SESSION_ID>` resumes a previous interactive session
* `codex resume --last` resumes the most recent local session
* `codex exec resume` works for non-interactive tasks too
* session IDs can be found under `~/.codex/sessions/`
* resumed runs keep the original transcript, plan history, and approvals
* `codex fork` creates a new thread from a previous interactive session while preserving transcript history. ([OpenAI Developers][4])

Why this matters:

* these official persistence semantics are **documented for CLI sessions**
* they are **not** documented for `codex mcp-server` threads. ([OpenAI Developers][1])

So do **not** build the MCP integration on the assumption that MCP `threadId` behaves like `codex resume` session IDs across restarts.

---

## 8. Recommended implementation contract

## 8.1 App-level identifiers

Use stable app IDs you control:

* `private_main`
* `group_<chat_id>_topic_<topic_id>`

These are your source of truth.

## 8.2 Runtime session registry

Keep a registry in the repo, for example:

```json
{
  "private_main": {
    "kind": "private",
    "codex_thread_id": "019bbb20-bff6-7130-83aa-bf45ab33250e",
    "status": "live",
    "created_at": "2026-03-08T14:00:00Z",
    "last_active_at": "2026-03-08T14:20:00Z",
    "restart_generation": 3
  },
  "group_12345_topic_7": {
    "kind": "group_topic",
    "codex_thread_id": "019bbb20-c111-7120-9999-aaaaaaaaaaaa",
    "status": "live",
    "created_at": "2026-03-08T13:00:00Z",
    "last_active_at": "2026-03-08T14:10:00Z",
    "restart_generation": 3
  }
}
```

## 8.3 Restart generation

Track a `restart_generation` or server epoch.

When the agent process starts:

* create a new runtime generation,
* mark all previously live MCP thread mappings as stale,
* lazily rehydrate each app session the next time a message arrives.

Because restart persistence for MCP thread IDs is not documented, this avoids false assumptions. ([OpenAI Developers][2])

---

## 9. Process model to avoid cold starts

## 9.1 Single shared MCP server process

Run exactly one long-lived child process:

```bash
codex mcp-server --cd /path/to/agent-repo --profile telegram-agent
```

or equivalent with explicit flags like model/sandbox if you do not want everything in the profile. The docs confirm `codex mcp-server` inherits global overrides, and profiles are a documented way to define defaults. ([OpenAI Developers][1])

## 9.2 Why one server

One always-on server gives you the best startup behavior because:

* you pay the process startup cost once,
* Codex stays alive across multiple turns,
* each topic/private flow gets a logical thread in that one server. ([OpenAI Developers][2])

## 9.3 When to start a new thread

Start a new `codex` thread only when:

* app session has no mapping yet,
* or the mapping belongs to an earlier server generation,
* or the live thread is known broken/unusable.

Otherwise use `codex-reply`.

---

## 10. Message handling algorithm

## 10.1 On incoming Telegram message

1. Resolve app session key:

    * private → `private_main`
    * group topic → `group_<chat_id>_topic_<topic_id>`

2. Check session registry.

3. If there is a live thread for the current server generation:

    * call `codex-reply`.

4. Otherwise:

    * build a hydration prompt from repo-backed summary/task/memory state,
    * call `codex`,
    * store returned `structuredContent.threadId`.

This is the safest design because only `codex` creates a thread and only `codex-reply` continues one, per the official API. ([OpenAI Developers][2])

## 10.2 Hydration prompt after restart

Since MCP restart persistence is undocumented, hydration must reconstruct conversational state from the repo. The hydration prompt should include:

* session identity
* current task state
* compact topic summary
* shared memory pointers
* repo status if relevant
* explicit instructions that this is a continuation of prior work in a new runtime thread

This matches your earlier architecture where the repo is the source of truth.

---

## 11. Exact recommended MCP call patterns

## 11.1 Start a new thread for private chat

```json
{
  "tool": "codex",
  "arguments": {
    "prompt": "You are continuing the private main Telegram conversation. Read the repo-backed memory, tasks, and summary files in this workspace before replying. The current user message is: ...",
    "cwd": "/path/to/agent-repo",
    "profile": "telegram-agent",
    "sandbox": "workspace-write",
    "approval-policy": "on-request",
    "include-plan-tool": true
  }
}
```

This matches the official `codex` tool schema. ([OpenAI Developers][2])

## 11.2 Continue an existing thread

```json
{
  "tool": "codex-reply",
  "arguments": {
    "threadId": "019bbb20-bff6-7130-83aa-bf45ab33250e",
    "prompt": "New Telegram message in private_main: ..."
  }
}
```

This matches the official `codex-reply` schema. ([OpenAI Developers][2])

## 11.3 Start a new thread for a group topic after restart

```json
{
  "tool": "codex",
  "arguments": {
    "prompt": "You are resuming Telegram group topic group_12345_topic_7 after a service restart. There is no guaranteed prior MCP thread continuity. Reconstruct context from the repo: read memory/summaries/group_12345_topic_7.md, relevant tasks, and global memory before replying. New user message: ...",
    "cwd": "/path/to/agent-repo",
    "profile": "telegram-agent",
    "sandbox": "workspace-write",
    "approval-policy": "on-request",
    "include-plan-tool": true
  }
}
```

This is not a new official API; it is the correct usage pattern built on top of the official `codex` tool. ([OpenAI Developers][2])

---

## 12. Recommended Codex profile for this system

Create a profile in `~/.codex/config.toml`, because profiles are officially supported and are the cleanest way to keep your MCP invocation small. ([OpenAI Developers][3])

Example:

```toml
profile = "telegram-agent"

[profiles.telegram-agent]
model = "gpt-5-codex"
sandbox_mode = "workspace-write"
web_search = "cached"
model_auto_compact_token_limit = 200000

[profiles.telegram-agent.history]
persistence = "save-all"
max_bytes = 268435456
```

Notes:

* `profile` and `profiles.<name>.*` are documented. ([OpenAI Developers][3])
* `model`, `model_auto_compact_token_limit`, and history settings are documented. ([OpenAI Developers][3])
* `sandbox_mode` is the documented config key, while the MCP tool argument uses `sandbox`. ([OpenAI Developers][3])

For your use case I would keep `workspace-write` and avoid `danger-full-access` unless you really need it.

---

## 13. Mac mini process supervision

Since you said to assume a Mac mini, treat `codex mcp-server` like an always-on local service:

* launch it under a supervisor,
* keep stdio attached to your MCP client process,
* restart it automatically if it crashes,
* increment server generation on restart,
* lazily recreate stale threads from repo state.

This recommendation is architectural, but it follows directly from the fact that the official transport is stdio and the process exits when the downstream client closes the connection. ([OpenAI Developers][1])

---

## 14. What the implementation agent must **not** assume

The implementation must **not** assume any of the following unless OpenAI documents them later:

* that an MCP `threadId` can be caller-chosen,
* that an MCP `threadId` is resumable after server restart,
* that MCP threads are stored in `~/.codex/sessions/`,
* that CLI `resume` can be used to continue an MCP-server `threadId`. ([OpenAI Developers][2])

The docs only clearly document local session resume/fork for CLI interactive and exec sessions, not for MCP-server threads. ([OpenAI Developers][1])

---

## 15. Best-practice conclusion

For **your exact goal**—persistent Telegram chats with minimal cold start—the best design using official Codex MCP behavior is:

* run **one long-lived `codex mcp-server` process**,
* keep it alive as long as your service is alive,
* map each Telegram flow to your own stable app session key,
* map each app session key to the server-returned `threadId`,
* use `codex-reply` while the server stays up,
* after restart, create a fresh MCP thread and reconstruct context from the repo.

That gives you the warm-session behavior you want without relying on undocumented restart semantics. ([OpenAI Developers][2])

One important opinion from me: if **true restart-resumable server-side threads** become a hard requirement, `codex app-server` is the cleaner official fit because its docs explicitly mention `thread/start`, `thread/resume`, and `thread/fork`. For `codex mcp-server`, I would build assuming **warm continuity during uptime, repo-driven recovery across restarts**. ([OpenAI Developers][5])

If you want, I can turn this into a ready-to-drop `CODEX_MCP_SPEC.md` and then write the matching `config.toml` plus a Python MCP client skeleton for the Telegram bot.

[1]: https://developers.openai.com/codex/cli/reference/ "Command line options"
[2]: https://developers.openai.com/codex/guides/agents-sdk/ "Use Codex with the Agents SDK"
[3]: https://developers.openai.com/codex/config-reference/ "Configuration Reference"
[4]: https://developers.openai.com/codex/cli/features/ "Codex CLI features"
[5]: https://developers.openai.com/codex/app-server/?utm_source=chatgpt.com "Codex App Server"

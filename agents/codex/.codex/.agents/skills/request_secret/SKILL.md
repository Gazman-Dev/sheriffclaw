---
name: request_secret
description: Use this skill when you realize you need an API key, password, or token to complete a task. Do NOT ask the user for the secret directly.
---

# Request a Secret via Sheriff

## Goal
Securely request a credential from the user's Sheriff vault without exposing the secret in plaintext to the chat.

## Preconditions
- You have identified that a CLI tool or script requires an API key or authentication token.
- You know the target domain or tool name.

## Workflow
1. Determine a concise, snake_case handle for the secret (e.g., `github_token`, `aws_access_key`).
2. Formulate a 1-sentence explanation of why you need it (e.g., "Need GitHub token to open a PR").
3. Use your execution environment to invoke the Sheriff request tool (or write the request via the file protocol as instructed by the Sheriff environment tools).
4. Wait for the file system state to indicate that the secret has been approved and injected into your environment.

## Outputs
- A pending file status letting the user know you have dispatched a secure Sheriff request.
- Do NOT output the secret handle value in your response.
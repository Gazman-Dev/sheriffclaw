from __future__ import annotations


SERVICE_PORTS: dict[str, int] = {
    "sheriff-secrets": 47601,
    "sheriff-policy": 47602,
    "sheriff-requests": 47603,
    "sheriff-web": 47604,
    "sheriff-tools": 47605,
    "sheriff-gateway": 47606,
    "sheriff-tg-gate": 47607,
    "sheriff-cli-gate": 47608,
    "sheriff-updater": 47609,
    "sheriff-scheduler": 47612,
    "codex-mcp-host": 47610,
    "ai-tg-llm": 47611,
    "sheriff-chat-proxy": 47613,
}


def rpc_endpoint(service: str) -> tuple[str, int] | None:
    port = SERVICE_PORTS.get(service)
    if port is None:
        return None
    return "127.0.0.1", port


def rpc_service_names() -> list[str]:
    return list(SERVICE_PORTS.keys())

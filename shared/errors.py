class ProtocolError(RuntimeError):
    """Raised when NDJSON protocol contracts are violated."""


class ServiceCrashedError(RuntimeError):
    """Raised when a child service exits during a request."""

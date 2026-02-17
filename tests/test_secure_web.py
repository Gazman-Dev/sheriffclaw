import urllib.request
import pytest
from unittest.mock import MagicMock
from shared.secure_web import SecureWebRequester
from shared.policy import GatewayPolicy

def test_request_https_constructs_correct_request(monkeypatch):
    policy = GatewayPolicy({"api.github.com"})
    monkeypatch.setattr(policy, "validate_host", lambda h: None)

    requester = SecureWebRequester(policy)

    # Mock urllib response
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = b'{"ok": true}'
    mock_response.headers.items.return_value = [("Content-Type", "application/json")]

    mock_urlopen = MagicMock()
    mock_urlopen.__enter__.return_value = mock_response

    # Capture request
    captured_req = None
    def capture(req, **kwargs):
        nonlocal captured_req
        captured_req = req
        return mock_urlopen
    monkeypatch.setattr(urllib.request, "urlopen", capture)

    payload = {
        "method": "POST",
        "host": "api.github.com",
        "path": "/graphql",
        "headers": {
            "Accept": "application/json",
            "X-Not-Allowed": "bad"
        },
        "body": "{}"
    }
    # Secrets passed from SheriffGateway -> SheriffWeb -> Requester
    resolved_secrets = {"Authorization": "Bearer token123"}

    result = requester.request_https(payload, resolved_secrets)

    assert result["status"] == 200
    assert result["body"] == '{"ok": true}'

    # Verify Request object
    assert captured_req.full_url == "https://api.github.com/graphql"
    assert captured_req.method == "POST"

    # Check headers filtering
    headers = captured_req.headers
    assert headers["Accept"] == "application/json"
    assert headers["Authorization"] == "Bearer token123"
    assert "X-Not-Allowed" not in headers  # Not in ALLOWED_HEADERS

def test_request_https_enforces_policy():
    policy = GatewayPolicy(set()) # Empty allowlist
    requester = SecureWebRequester(policy)

    with pytest.raises(ValueError, match="host not allowlisted"):
        requester.request_https({"host": "evil.com"}, {})
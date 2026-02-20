from services.sheriff_ctl.ctl import build_parser


def test_configure_llm_command_parses():
    parser = build_parser()
    args = parser.parse_args(["configure-llm", "--provider", "openai-codex", "--api-key", "sk-123", "--master-password", "mp"])
    assert args.provider == "openai-codex"
    assert args.api_key == "sk-123"
    assert args.master_password == "mp"

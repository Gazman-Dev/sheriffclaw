from services.sheriff_ctl.ctl import build_parser


def test_configure_llm_command_parses():
    parser = build_parser()
    args = parser.parse_args(["configure-llm", "--provider", "openai-codex", "--api-key", "sk-123", "--master-password", "mp"])
    assert args.provider == "openai-codex"
    assert args.api_key == "sk-123"
    assert args.master_password == "mp"


def test_onboarding_alias_parses():
    parser = build_parser()
    args = parser.parse_args(["onboarding", "--master-password", "x"])
    assert args.master_password == "x"


def test_reinstall_command_removed():
    parser = build_parser()
    try:
        parser.parse_args(["reinstall"])
        assert False, "expected SystemExit"
    except SystemExit:
        pass


def test_logout_llm_parses():
    parser = build_parser()
    args = parser.parse_args(["logout-llm", "--master-password", "x"])
    assert args.master_password == "x"


def test_factory_reset_parses():
    parser = build_parser()
    args = parser.parse_args(["factory-reset", "--yes"])
    assert args.yes is True


def test_debug_parses():
    parser = build_parser()
    args = parser.parse_args(["debug", "on"])
    assert args.value == "on"


def test_update_parses():
    parser = build_parser()
    args = parser.parse_args(["update", "--master-password", "x", "--no-pull"])
    assert args.master_password == "x"
    assert args.no_pull is True

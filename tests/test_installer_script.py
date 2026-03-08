from pathlib import Path


def test_installer_shebang_is_plain_bash():
    first_line = Path("sheriffclaw.sh").read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "#!/bin/bash"

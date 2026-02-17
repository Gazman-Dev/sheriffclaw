import pytest
import sys
from shared.tools_exec import ToolExecutor

def test_tool_exec_rejects_shell_operators(tmp_path):
    executor = ToolExecutor(tmp_path)

    # Should fail due to pipe
    with pytest.raises(ValueError, match="shell tokens"):
        executor.exec(["echo", "hello", "|", "sh"])

    # Should fail due to semicolon
    with pytest.raises(ValueError, match="shell tokens"):
        executor.exec(["ls", ";", "rm", "-rf", "/"])

def test_tool_exec_runs_subprocess(tmp_path):
    executor = ToolExecutor(tmp_path)
    # FIXED: Use sys.executable for cross-platform safety
    res = executor.exec([sys.executable, "-c", "print('hello world')"])

    assert res["code"] == 0
    assert "hello world" in res["stdout"]

def test_tool_save_load_output(tmp_path):
    executor = ToolExecutor(tmp_path)
    run_id = "run-123"
    data = {"stdout": "secret", "stderr": "", "code": 0}

    executor.save_output(run_id, data)

    loaded = executor.load_output(run_id)
    assert loaded == data

    assert executor.load_output("non-existent") is None
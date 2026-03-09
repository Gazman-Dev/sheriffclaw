$ErrorActionPreference = "Stop"

Write-Host "Running Python setup..."
python -m pip install -U pip | Out-Null
python -m pip install -e ".[dev]" | Out-Null

Write-Host "Running pytest..."
pytest -q

Write-Host "Note: Bash E2E scenarios are skipped in Windows Native mode. They will run in the Linux Docker container."

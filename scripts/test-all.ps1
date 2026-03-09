$ErrorActionPreference = "Stop"

Write-Host "== Windows Native Tests =="
.\scripts\test.ps1

Write-Host "`n== Linux Container Tests =="
docker compose run --rm test-linux

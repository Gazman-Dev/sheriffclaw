# -*- mode: python ; coding: utf-8 -*-

block_cipher = None


def build(name: str, script: str):
    a = Analysis([script], pathex=[], binaries=[], datas=[], hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[])
    pyz = PYZ(a.pure)
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=name, debug=False, bootloader_ignore_signals=False, strip=False, upx=True, console=True)
    return exe

agent = build("sheriff-agent", "run_agent.py")
gate = build("sheriff-gate", "run_gate.py")

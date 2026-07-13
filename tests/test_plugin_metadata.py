from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_local_plugin_manifest_and_assets_are_complete() -> None:
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    mcp_config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))

    assert manifest["mcpServers"] == "./.mcp.json"
    assert manifest["interface"]["defaultPrompt"]
    assert manifest["interface"]["logo"] == "./assets/logo.svg"
    assert manifest["interface"]["composerIcon"] == "./assets/logo.svg"
    assert mcp_config["yahoo-shopping"]["url"].endswith("/mcp")
    assert (ROOT / "assets" / "logo.svg").read_text(encoding="utf-8").startswith("<svg ")

from __future__ import annotations

from html import escape
from typing import Any, Mapping


def render_preview_svg(preview: Mapping[str, Any]) -> str:
    """Render a bounded, text-free mutation summary for hosts that display SVG."""

    status = escape(str(preview.get("status", "preview")))
    operation_count = len(preview.get("normalized_operations") or [])
    affected_count = len(preview.get("affected_nodes") or [])
    conflict_count = len(preview.get("conflicts") or [])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="180" viewBox="0 0 640 180" role="img" aria-labelledby="title desc">
<title id="title">Agentic Memory update preview</title>
<desc id="desc">{operation_count} operations, {affected_count} affected nodes, {conflict_count} conflicts. Confirmation is required.</desc>
<rect width="640" height="180" rx="16" fill="#f7f7f8"/>
<text x="28" y="42" font-family="system-ui,sans-serif" font-size="20" font-weight="700" fill="#111827">Agentic Memory Preview</text>
<text x="28" y="72" font-family="system-ui,sans-serif" font-size="14" fill="#374151">Status: {status}</text>
<text x="28" y="108" font-family="system-ui,sans-serif" font-size="16" fill="#111827">Operations: {operation_count}</text>
<text x="220" y="108" font-family="system-ui,sans-serif" font-size="16" fill="#111827">Affected nodes: {affected_count}</text>
<text x="440" y="108" font-family="system-ui,sans-serif" font-size="16" fill="#111827">Conflicts: {conflict_count}</text>
<text x="28" y="148" font-family="system-ui,sans-serif" font-size="14" fill="#9a3412">Review and explicitly confirm before Apply.</text>
</svg>"""

# Owner: Charbel

"""Serves the widget loader script.

Real implementation: Phase 4 (Vite + React bundle).
This stub proves the <script> tag loads and logs the widget_id.
"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter()


@router.get("/widget.js", response_class=PlainTextResponse)
def serve_widget_js() -> str:
    """Serves the widget loader script stub."""
    return """
// Concierge Widget Loader — stub
// Real implementation: Phase 4
console.log('[Concierge] widget.js loaded');
const widgetId = document.currentScript.getAttribute('data-widget-id');
if (!widgetId) {
  console.error('[Concierge] data-widget-id is required');
} else {
  console.log('[Concierge] widget_id:', widgetId);
  // TODO Phase 4: exchange widget_id for token, inject chat iframe
}
"""

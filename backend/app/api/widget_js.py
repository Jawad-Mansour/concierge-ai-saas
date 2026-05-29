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
    """Serves the widget loader script."""
    return """(function() {
  const script = document.currentScript;
  const widgetId = script.getAttribute('data-widget-id');
  if (!widgetId) {
    console.error('[Concierge] data-widget-id is required');
    return;
  }
  console.log('[Concierge] widget.js loaded, widget_id:', widgetId);

  const iframe = document.createElement('iframe');
  iframe.src = 'http://localhost:8081/';
  iframe.style.cssText = [
    'position:fixed',
    'bottom:0',
    'right:0',
    'width:400px',
    'height:600px',
    'border:none',
    'z-index:9999',
    'background:transparent',
  ].join(';');
  iframe.allow = 'microphone';
  iframe.title = 'Concierge Chat Widget';
  document.body.appendChild(iframe);
})();
"""

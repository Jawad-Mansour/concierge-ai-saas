// Owner: Charbel

(function() {
  const script = document.currentScript;
  const widgetId = script.getAttribute('data-widget-id');
  if (!widgetId) {
    console.error('[Concierge] data-widget-id is required');
    return;
  }
  console.log('[Concierge] widget.js loaded, widget_id:', widgetId);

  // Create iframe pointing to the widget server
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

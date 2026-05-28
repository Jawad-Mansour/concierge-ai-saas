# Owner: Charbel

"""CSP middleware — sets frame-ancestors on all API responses.

The frame-ancestors directive tells browsers which pages may embed
this content in an iframe. This is set permissively here (any origin
can embed the widget endpoint) because origin control happens at the
widget token level, not the CSP level. The demo/blocked-host page
enforces blocking via its own Content-Security-Policy header.
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class CSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        # Allow embedding from any origin — actual auth is via signed token.
        # The blocked-host demo uses the HOST PAGE's CSP to block, not this.
        response.headers["X-Frame-Options"] = "ALLOWALL"
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
        return response

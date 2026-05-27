# Owner: Charbel
# Widget auth tests — Phase 5 implementation.
# These define the contract. All skipped until widget_auth_service lands.
# Remove skip markers one by one as you implement each piece.

import pytest


@pytest.mark.skip(reason="Phase 5 — widget_auth_service not implemented")
def test_valid_origin_returns_signed_jwt():
    """POST /widget/token with valid widget_id + allowed origin
    returns a JWT signed with secret/concierge/widget_jwt."""
    pass


@pytest.mark.skip(reason="Phase 5 — widget_auth_service not implemented")
def test_disallowed_origin_returns_403():
    """POST /widget/token from an origin not in allowed_origins
    returns HTTP 403. CORS error alone is not sufficient."""
    pass


@pytest.mark.skip(reason="Phase 5 — widget_auth_service not implemented")
def test_expired_token_rejected():
    """A widget JWT past its 900s TTL is rejected with 401."""
    pass


@pytest.mark.skip(reason="Phase 5 — widget_auth_service not implemented")
def test_token_from_different_tenant_rejected():
    """A valid token issued for Tenant A cannot be used on Tenant B."""
    pass


@pytest.mark.skip(reason="Phase 5 — widget_auth_service not implemented")
def test_raw_curl_no_token_returns_401():
    """Direct API call with no widget token returns 401.
    Proves CORS alone does not protect the endpoint."""
    pass


@pytest.mark.skip(reason="Phase 5 — widget_auth_service not implemented")
def test_server_side_origin_check_not_just_cors():
    """Server validates origin in the request handler, not just
    via CORS headers. A spoofed Origin header is rejected."""
    pass

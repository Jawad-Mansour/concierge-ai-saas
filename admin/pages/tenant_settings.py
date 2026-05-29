# Owner: Charbel

import base64
import json
from datetime import datetime, timezone

import streamlit as st


def _decode_jwt_payload(token: str) -> dict:
    """Base64-decode the JWT payload segment without verifying the signature."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return {}


def main() -> None:
    if "token" not in st.session_state:
        st.error("Not authenticated.")
        st.stop()

    st.title("Tenant settings")

    claims = _decode_jwt_payload(st.session_state["token"])
    if not claims:
        st.error("Could not decode token — please sign out and sign back in.")
        return

    exp = claims.get("exp")
    if exp:
        remaining = exp - datetime.now(timezone.utc).timestamp()
        if remaining > 0:
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            expiry_label = f"{mins}m {secs}s"
        else:
            expiry_label = "expired"
    else:
        expiry_label = "—"

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Role", claims.get("role", "—"))
        st.metric("Token expires", expiry_label)
    with col2:
        st.metric("Tenant ID", "")
        st.code(claims.get("tenant_id", "—"), language=None)
        st.metric("User ID", "")
        st.code(claims.get("sub") or "widget visitor", language=None)

    st.caption("Refresh page to update countdown.")
    st.divider()
    st.info("Session persists via URL token. Log out to end session.")


main()

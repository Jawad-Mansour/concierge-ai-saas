# Owner: Charbel

import os

import requests
import streamlit as st
import streamlit.components.v1 as components

API_URL = os.environ.get("API_URL", "http://localhost:8000")

_ALL_TOOLS = ["rag_search", "capture_lead", "escalate"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state['token']}"}


def _fetch_config() -> dict | None:
    resp = requests.get(f"{API_URL}/admin/widget-config", headers=_headers(), timeout=10)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    if "token" not in st.session_state:
        st.error("Not authenticated.")
        st.stop()

    flash = st.session_state.pop("wc_flash", None)
    if flash:
        if flash["type"] == "success":
            st.success(flash["message"])
        elif flash["type"] == "error":
            st.error(flash["message"])

    st.header("Widget config")

    # ── A: Current config ────────────────────────────────────────────────────
    st.subheader("Current config")
    try:
        config = _fetch_config()
    except requests.RequestException as exc:
        st.error(f"Backend error: {exc}")
        return

    if config is None:
        st.info("No widget config yet for this tenant. Use the form below to create one.")
        config = {}
    else:
        current_theme = config.get("theme", {})
        st.metric("Widget ID", config.get("widget_id", "—"))
        st.write("**Allowed origins:**")
        for origin in config.get("allowed_origins", []):
            st.code(origin, language=None)
        st.write("**Greeting:**", config.get("greeting", "—"))
        st.color_picker(
            "Primary color",
            value=current_theme.get("primary_color", "#A7C080"),
            disabled=True,
            key="wc_display_primary",
        )
        st.multiselect(
            "Enabled tools",
            options=_ALL_TOOLS,
            default=config.get("enabled_tools", []),
            disabled=True,
            key="wc_display_tools",
        )

    st.divider()

    # ── B: Edit config (no form wrapper — live color picker) ─────────────────
    st.subheader("Edit config")

    current_theme = config.get("theme", {})
    current_origins = "\n".join(config.get("allowed_origins", []))
    current_primary = current_theme.get("primary_color", "#A7C080")
    current_greeting = config.get("greeting", "Hi! How can I help you today?")
    current_tools = config.get("enabled_tools", [])

    origins_raw = st.text_area(
        "Allowed origins (one per line)",
        value=current_origins,
        height=100,
        help="e.g. https://example.com",
        key="wc_edit_origins",
    )
    primary_color = st.color_picker(
        "Primary color", value=current_primary, key="wc_edit_primary"
    )
    greeting = st.text_input(
        "Greeting message", value=current_greeting, key="wc_edit_greeting"
    )
    sel_tools = st.multiselect(
        "Enabled tools", options=_ALL_TOOLS, default=current_tools, key="wc_edit_tools"
    )

    if st.button("Save", use_container_width=True, key="wc_save"):
        allowed_origins = [o.strip() for o in origins_raw.splitlines() if o.strip()]
        payload = {
            "allowed_origins": allowed_origins,
            "theme": {**current_theme, "primary_color": primary_color},
            "greeting": greeting,
            "enabled_tools": sel_tools,
        }
        try:
            resp = requests.put(
                f"{API_URL}/admin/widget-config",
                json=payload,
                headers=_headers(),
                timeout=10,
            )
            resp.raise_for_status()
            for k in ["wc_edit_origins", "wc_edit_primary", "wc_edit_greeting", "wc_edit_tools",
                      "wc_display_primary", "wc_display_tools"]:
                st.session_state.pop(k, None)
            st.session_state["wc_flash"] = {"type": "success", "message": "Saved successfully."}
            st.rerun()
        except requests.RequestException as exc:
            st.session_state["wc_flash"] = {"type": "error", "message": f"Save failed: {exc}"}
            st.rerun()

    st.divider()

    # ── C: Embed snippet ─────────────────────────────────────────────────────
    st.subheader("Embed snippet")
    if config.get("widget_id"):
        try:
            snip_resp = requests.get(
                f"{API_URL}/admin/widget-config/embed-snippet",
                headers=_headers(),
                timeout=10,
            )
            snip_resp.raise_for_status()
            st.code(snip_resp.json()["snippet"], language="html")
            st.caption("Paste this tag into your website's HTML to embed the widget.")
        except requests.RequestException as exc:
            st.error(f"Could not fetch snippet: {exc}")
    else:
        st.caption("Save a config first to generate the embed snippet.")

    st.divider()

    # ── D: Widget preview ────────────────────────────────────────────────────
    st.subheader("Widget preview")
    st.caption("Live preview of the allowed host (localhost:8080)")
    components.iframe("http://localhost:8080", height=400, scrolling=True)

    st.divider()

    # ── E: Test origin validation ─────────────────────────────────────────────
    st.subheader("Test origin validation")
    st.caption(
        "Simulate a token request from a given origin to verify your allowlist."
    )
    first_origin = (config.get("allowed_origins") or [""])[0]
    test_origin = st.text_input(
        "Origin to test",
        value=first_origin,
        placeholder="https://example.com",
        key="wc_test_origin",
    )
    if st.button("Request token", key="wc_request_token") and test_origin:
        if not config.get("widget_id"):
            st.error("No widget_id — save a config first.")
        else:
            try:
                tok_resp = requests.post(
                    f"{API_URL}/widget/token",
                    json={"widget_id": config["widget_id"], "origin": test_origin},
                    timeout=10,
                )
                if tok_resp.status_code == 200:
                    st.success("✓ Token issued. Origin is allowed.")
                elif tok_resp.status_code == 403:
                    st.error("✗ Origin rejected — not in allowed_origins list.")
                else:
                    st.warning(f"Unexpected response: {tok_resp.status_code}")
            except requests.RequestException as exc:
                st.error(f"Request failed: {exc}")


main()

# Owner: Charbel

import os

import requests
import streamlit as st

st.set_page_config(page_title="Concierge Admin", layout="centered")

API_URL = os.environ.get("API_URL", "http://localhost:8000")
LOGIN_URL = f"{API_URL}/auth/login"


def _show_login() -> None:
    col_left, col_mid, col_right = st.columns([1, 2, 1])
    with col_mid:
        st.title("Concierge Admin")
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", use_container_width=True)

        if submitted:
            try:
                resp = requests.post(
                    LOGIN_URL,
                    json={"email": email, "password": password},
                    timeout=10,
                )
            except requests.RequestException as exc:
                st.error(f"Could not reach backend: {exc}")
                return

            if resp.status_code == 200:
                token = resp.json()["access_token"]
                st.session_state["token"] = token
                st.query_params["token"] = token
                st.rerun()
            else:
                st.error(f"Login failed ({resp.status_code}): {resp.text}")


def _show_logout_sidebar() -> None:
    with st.sidebar:
        st.markdown("**Concierge Admin**")
        st.divider()
        if st.button("Sign out", use_container_width=True):
            st.session_state.clear()
            st.query_params.clear()
            st.rerun()


# ── Auth gate ────────────────────────────────────────────────────────────────

if "token" not in st.session_state:
    param_token = st.query_params.get("token")
    if param_token:
        st.session_state["token"] = param_token
    else:
        _show_login()
        st.stop()

# Always keep token in URL so refresh works on any page
st.query_params["token"] = st.session_state["token"]
_show_logout_sidebar()

# ── Pages ────────────────────────────────────────────────────────────────────


def _coming_soon_leads() -> None:
    st.info("Leads dashboard — coming soon.")


pg = st.navigation(
    {
        "Configuration": [
            st.Page("pages/widget_config.py", title="Widget config", icon=":material/widgets:"),
            st.Page(
                "pages/tenant_settings.py", title="Tenant settings", icon=":material/person:"
            ),
            st.Page(
                "pages/guardrails_config.py",
                title="Guardrails config",
                icon=":material/shield:",
            ),
        ],
        "Coming soon": [
            st.Page(_coming_soon_leads, title="Leads dashboard", icon=":material/bar_chart:"),
        ],
    }
)
pg.run()

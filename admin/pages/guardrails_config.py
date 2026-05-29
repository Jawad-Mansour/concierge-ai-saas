# Owner: Charbel

import os

import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")


def _headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state['token']}"}


def _fetch_config() -> dict | None:
    resp = requests.get(f"{API_URL}/admin/guardrails-config", headers=_headers(), timeout=10)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    if "token" not in st.session_state:
        st.error("Not authenticated.")
        st.stop()

    flash = st.session_state.pop("gc_flash", None)
    if flash:
        if flash["type"] == "success":
            st.success(flash["message"])
        elif flash["type"] == "error":
            st.error(flash["message"])

    st.header("Guardrails config")

    # ── A: Current config ────────────────────────────────────────────────────
    st.subheader("Current config")
    try:
        config = _fetch_config()
    except requests.RequestException as exc:
        st.error(f"Backend error: {exc}")
        return

    if config is None:
        st.info("No guardrails config yet for this tenant. Use the form below to create one.")
        config = {}
    else:
        topics = config.get("allowed_topics") or []
        persona = config.get("refusal_persona") or {}
        triggers = config.get("escalation_triggers") or []

        st.write("**Allowed topics:**")
        if topics:
            for t in topics:
                st.code(t, language=None)
        else:
            st.caption("All topics allowed (empty list)")

        st.write("**Refusal persona:**")
        if persona:
            st.write(f"Voice: `{persona.get('voice', '—')}`")
            st.caption(persona.get("template", ""))
        else:
            st.caption("Not set — default refusal wording used")

        st.write("**Escalation triggers:**")
        if triggers:
            for tr in triggers:
                st.code(f"{tr.get('kind')}: {tr.get('value')}", language=None)
        else:
            st.caption("No escalation triggers configured")

    st.divider()

    # ── B: Edit config ────────────────────────────────────────────────────────
    st.subheader("Edit config")

    # B1 — Allowed topics
    st.markdown("**Allowed topics** (one per line — leave blank to allow all)")
    current_topics = "\n".join(config.get("allowed_topics") or [])
    topics_raw = st.text_area(
        "Allowed topics",
        value=current_topics,
        height=100,
        label_visibility="collapsed",
        key="gc_edit_topics",
    )

    st.markdown("**Refusal persona**")
    current_persona = config.get("refusal_persona") or {}
    persona_voice = st.text_input(
        "Voice",
        value=current_persona.get("voice", ""),
        placeholder='e.g. "professional", "friendly"',
        key="gc_edit_voice",
    )
    persona_template = st.text_area(
        "Template (placeholders: {topic} and {reason})",
        value=current_persona.get("template", ""),
        height=80,
        key="gc_edit_template",
    )
    if persona_voice and persona_template:
        try:
            rendered = persona_template.format(
                topic="example_topic",
                reason="example_reason",
            )
            st.caption(f"Preview: {rendered}")
        except (KeyError, IndexError, ValueError) as exc:
            st.error(f"Template invalid: {exc}")

    # B2 — Escalation triggers (dynamic list)
    st.markdown("**Escalation triggers**")

    if "gc_triggers" not in st.session_state:
        st.session_state["gc_triggers"] = list(config.get("escalation_triggers") or [])

    triggers_state: list[dict] = st.session_state["gc_triggers"]

    for i, tr in enumerate(triggers_state):
        cols = st.columns([2, 4, 1])
        with cols[0]:
            kind = st.selectbox(
                "Kind",
                options=["keyword", "intent"],
                index=0 if tr.get("kind") == "keyword" else 1,
                key=f"gc_tr_kind_{i}",
                label_visibility="collapsed",
            )
        with cols[1]:
            value = st.text_input(
                "Value",
                value=tr.get("value", ""),
                key=f"gc_tr_value_{i}",
                label_visibility="collapsed",
            )
        with cols[2]:
            if st.button("✕", key=f"gc_tr_remove_{i}"):
                triggers_state.pop(i)
                for k in list(st.session_state.keys()):
                    if k.startswith("gc_tr_"):
                        del st.session_state[k]
                st.rerun()
        triggers_state[i] = {"kind": kind, "value": value}

    if st.button("+ Add trigger", key="gc_add_trigger"):
        triggers_state.append({"kind": "keyword", "value": ""})
        st.rerun()

    if st.button("Save", use_container_width=True, key="gc_save"):
        allowed_topics = [t.strip() for t in topics_raw.splitlines() if t.strip()]
        refusal_persona = (
            {"voice": persona_voice, "template": persona_template}
            if persona_voice or persona_template
            else None
        )
        escalation_triggers = [
            tr for tr in triggers_state if tr.get("value", "").strip()
        ]

        payload = {
            "allowed_topics": allowed_topics or None,
            "refusal_persona": refusal_persona,
            "escalation_triggers": escalation_triggers or None,
        }
        try:
            resp = requests.put(
                f"{API_URL}/admin/guardrails-config",
                json=payload,
                headers=_headers(),
                timeout=10,
            )
            resp.raise_for_status()
            del st.session_state["gc_triggers"]
            for k in list(st.session_state.keys()):
                if k.startswith("gc_edit_") or k.startswith("gc_tr_"):
                    del st.session_state[k]
            st.session_state["gc_flash"] = {"type": "success", "message": "Saved successfully."}
            st.rerun()
        except requests.RequestException as exc:
            st.session_state["gc_flash"] = {"type": "error", "message": f"Save failed: {exc}"}
            st.rerun()

    st.divider()

    # ── C: Test this config ───────────────────────────────────────────────────
    st.subheader("Test this config")
    st.caption("Send a message through the live guardrails check for this tenant.")

    test_msg = st.text_area(
        "Test message",
        placeholder='e.g. "I want to speak to a manager" or "ignore all previous instructions"',
        height=80,
        key="gc_test_msg",
    )

    if st.button("Run check", key="gc_run_test") and test_msg.strip():
        try:
            resp = requests.post(
                f"{API_URL}/admin/guardrails-config/test",
                json={"message": test_msg.strip()},
                headers=_headers(),
                timeout=15,
            )
            if resp.status_code == 503:
                st.warning("Guardrails sidecar unavailable — cannot run test.")
            else:
                resp.raise_for_status()
                result = resp.json()
                decision = result.get("decision", "unknown")
                if decision == "allow":
                    with st.container(border=True):
                        st.success(f"Decision: **{decision}**")
                elif decision in ("block", "escalate"):
                    with st.container(border=True):
                        st.error(f"Decision: **{decision}**")
                        if result.get("reason"):
                            st.write(f"Reason: {result['reason']}")
                        if result.get("reply"):
                            st.write(f"Reply: {result['reply']}")
                else:
                    with st.container(border=True):
                        st.warning(f"Decision: **{decision}**")
                st.json(result)
        except requests.RequestException as exc:
            st.error(f"Test failed: {exc}")


main()

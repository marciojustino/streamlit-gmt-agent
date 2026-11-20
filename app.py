from __future__ import annotations

import uuid
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from gmt.auth import has_oidc_configuration
from gmt.config import ConfigurationError, load_config
from gmt.contracts import OrchestratorInput
from gmt.orchestrator import build_system
from gmt.policy import sanitize_question


PROJECT_ROOT = Path(__file__).resolve().parent


@st.cache_resource
def load_application():
    config = load_config(PROJECT_ROOT / "config.yaml")
    return config, build_system(config, PROJECT_ROOT)


st.set_page_config(page_title="GMT — Consulta de jornadas", page_icon="ℹ️")
st.title("GMT — Consulta de jornadas")
st.caption("Protótipo local. Respostas factuais dependem de fontes aprovadas na base institucional.")

try:
    config, orchestrator = load_application()
except ConfigurationError:
    st.error("A configuração está indisponível ou inválida. A aplicação não pode continuar.")
    st.stop()

if config.audit_retention_days is None:
    st.error("Configure a retenção de auditoria conforme a política institucional antes de continuar.")
    st.stop()

if config.authorization_mode == "local":
    if config.environment != "local" or st.get_option("server.address") != "127.0.0.1":
        st.error("O modo local sem autenticação exige environment=local e bind em 127.0.0.1.")
        st.stop()
    user_id = "local-developer"
    st.warning("Modo local: autenticação desativada. Use somente dados fictícios.")
else:
    try:
        oidc_configured = has_oidc_configuration(st.secrets)
    except StreamlitSecretNotFoundError:
        oidc_configured = False

    if not oidc_configured:
        st.error("O login OIDC não está configurado; a autenticação foi interrompida.")
        st.info(
            "Configure [auth] em .streamlit/secrets.toml com redirect_uri, cookie_secret, "
            "client_id, client_secret e server_metadata_url. Obtenha os dados do provedor "
            "com o administrador institucional; não os envie por chat nem os versione."
        )
        st.stop()

    user = st.user
    if not getattr(user, "is_logged_in", False):
        st.warning("Autentique-se pelo provedor institucional antes de continuar.")
        if st.button("Entrar"):
            st.login()
        st.stop()

    user_id = getattr(user, "email", "")
    if not user_id or user_id.casefold() not in config.allowed_user_ids:
        st.error("Esta identidade não está autorizada para o ambiente configurado.")
        st.stop()

if not user_id:
    st.error("A identidade não foi confirmada.")
    st.stop()

session_id = st.session_state.setdefault("gmt_session_id", str(uuid.uuid4()))
messages = st.session_state.setdefault("gmt_messages", [])
for message in messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("status"):
            st.caption(f"Status: {message['status']} · Auditoria: {message['audit_id']}")
        for source in message.get("sources", []):
            st.caption(
                f"Fonte: {source['id']} · versão {source['version']} · "
                f"atualizada em {source['updated_at']}"
            )
        for limitation in message.get("limitations", []):
            st.caption(f"Limitação: {limitation}")

question = st.chat_input("Pergunte sobre uma jornada documentada")
if question:
    safe_question, contains_personal_data = sanitize_question(question)
    display_question = (
        "Mensagem com dados pessoais mascarados."
        if contains_personal_data
        else safe_question
    )
    st.session_state.gmt_messages.append({"role": "user", "content": display_question})
    with st.chat_message("user"):
        st.markdown(display_question)

    request = OrchestratorInput(
        session_id=session_id,
        user_id=user_id,
        question=question,
        environment=config.environment,
    )
    result = orchestrator.process(request)
    response = {
        "role": "assistant",
        "content": result.answer,
        "status": result.status.value,
        "audit_id": result.audit_id,
        "sources": [source.audit_dict() for source in result.sources],
        "limitations": list(result.limitations),
    }
    st.session_state.gmt_messages.append(response)
    max_messages = max(2, config.memory_max_turns * 2)
    del st.session_state.gmt_messages[:-max_messages]
    with st.chat_message("assistant"):
        st.markdown(result.answer)
        st.caption(f"Status: {result.status.value} · Auditoria: {result.audit_id}")
        for limitation in result.limitations:
            st.caption(f"Limitação: {limitation}")
        for source in response["sources"]:
            st.caption(
                f"Fonte: {source['id']} · versão {source['version']} · "
                f"atualizada em {source['updated_at']}"
            )

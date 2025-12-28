import asyncio
from pathlib import Path
import time
import os
import requests
import tempfile
import streamlit as st
import inngest
from dotenv import load_dotenv

# -------------------------------------------------
# Setup
# -------------------------------------------------

load_dotenv()

st.set_page_config(
    page_title="Security Policy RAG",
    page_icon="🔐",
    layout="wide",
)

# -------------------------------------------------
# Inngest helpers
# -------------------------------------------------

@st.cache_resource
def get_inngest_client() -> inngest.Inngest:
    return inngest.Inngest(app_id="policy", is_production=False)


def _inngest_api_base() -> str:
    return os.getenv("INNGEST_API_BASE", "http://127.0.0.1:8288/v1")


def fetch_runs(event_id: str) -> list[dict]:
    url = f"{_inngest_api_base()}/events/{event_id}/runs"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json().get("data", [])


def wait_for_run_output(event_id: str, timeout_s: float = 120.0) -> dict:
    start = time.time()
    while True:
        runs = fetch_runs(event_id)
        if runs:
            run = runs[0]
            status = run.get("status")
            if status in ("Completed", "Succeeded", "Success", "Finished"):
                return run.get("output") or {}
            if status in ("Failed", "Cancelled"):
                return {
                    "answer": "An internal error occurred. Please try again.",
                    "sources": [],
                    "roles": [],
                }
        if time.time() - start > timeout_s:
            return {
                "answer": "Timed out waiting for response. Please try again.",
                "sources": [],
                "roles": [],
            }
        time.sleep(0.4)


# -------------------------------------------------
# Backend calls
# -------------------------------------------------

async def send_event(name: str, data: dict) -> str:
    client = get_inngest_client()
    event_ids = await client.send(inngest.Event(name=name, data=data))
    return event_ids[0]


def list_documents() -> list[dict]:
    event_id = asyncio.run(send_event("rag/list_documents", {}))
    output = wait_for_run_output(event_id)
    return output.get("documents", [])


def delete_document(source_id: str):
    event_id = asyncio.run(
        send_event("rag/delete_document", {"source_id": source_id})
    )
    wait_for_run_output(event_id)


@st.cache_data
def get_documents_cached():
    return list_documents()


# -------------------------------------------------
# Sidebar – document management
# -------------------------------------------------

st.sidebar.title("📄 Documents")

st.sidebar.subheader("➕ Add document")

uploaded = st.sidebar.file_uploader(
    "Upload policy PDF",
    type=["pdf"],
    accept_multiple_files=False,
)

# policy_type = st.sidebar.text_input("Policy type", placeholder="Access Control")
# version = st.sidebar.text_input("Version", placeholder="2023.1")
# jurisdiction = st.sidebar.text_input("Jurisdiction", placeholder="EU")

if st.sidebar.button("🔄 Refresh documents"):
    get_documents_cached.clear()
    st.rerun()

if uploaded is not None:
    if st.sidebar.button("Ingest document"):
        with st.spinner("Ingesting document..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded.getbuffer())
                pdf_path = Path(tmp.name)

            event_id = asyncio.run(
                send_event(
                    "rag/ingest_pdf",
                    {
                        "pdf_path": str(pdf_path.resolve()),
                        "policy_type": "policy_type",
                        "version": "version",
                        "jurisdiction": "jurisdiction",
                    },
                )
            )

            wait_for_run_output(event_id)
            pdf_path.unlink(missing_ok=True)

        st.success("Document ingested")
        get_documents_cached.clear()
        st.rerun()

docs = get_documents_cached()

if "selected_docs" not in st.session_state:
    st.session_state.selected_docs = set(d["source_id"] for d in docs)

for doc in docs:
    sid = doc["source_id"]

    checked = sid in st.session_state.selected_docs
    new_checked = st.sidebar.checkbox(
        os.path.basename(sid),
        value=checked,
        key=f"chk_{sid}",
        help=f"{doc.get('policy_type','')} | v{doc.get('version','')} | {doc.get('jurisdiction','')}",
    )

    if new_checked:
        st.session_state.selected_docs.add(sid)
    else:
        st.session_state.selected_docs.discard(sid)

    if st.sidebar.button("❌ Delete", key=f"del_{sid}"):
        delete_document(sid)
        st.session_state.selected_docs.discard(sid)
        get_documents_cached.clear()
        st.rerun()

st.sidebar.caption("Unchecked documents are excluded from search.")

# -------------------------------------------------
# Main – query
# -------------------------------------------------

st.title("🔐 Security Policy Q&A")

with st.form("query_form"):
    question = st.text_input("Ask a question about the selected policies")
    submitted = st.form_submit_button(
        "Ask",
        disabled=len(st.session_state.selected_docs) == 0
    )

if not st.session_state.selected_docs:
    st.warning("No documents selected. Please select at least one document.")

if submitted and question.strip():
    with st.spinner("Searching policies..."):
        event_id = asyncio.run(
            send_event(
                "rag/query_pdf_ai",
                {
                    "question": question.strip(),
                    "allowed_sources": list(st.session_state.selected_docs),
                },
            )
        )

        output = wait_for_run_output(event_id)

    st.subheader("Answer")
    st.write(output.get("answer", "(No answer)"))

    roles = output.get("roles", [])
    if roles:
        st.subheader("Responsible roles")
        for r in roles:
            st.write(f"- {r}")

    sources = output.get("sources", [])
    if sources:
        st.subheader("Sources")
        for s in sources:
            st.markdown(
                f"- **{os.path.basename(s.get('document',''))}**"
                f"{' | ' + s['policy_type'] if s.get('policy_type') else ''}"
                f"{' | v' + s['version'] if s.get('version') else ''}"
                f"{' | ' + s['jurisdiction'] if s.get('jurisdiction') else ''}"
            )

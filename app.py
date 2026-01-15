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


def wait_for_document(source_id: str, timeout_s: float = 5.0, poll_interval: float = 0.5) -> list[dict] | None:
    start = time.time()
    while time.time() - start < timeout_s:
        docs = list_documents()
        if any(d["source_id"] == source_id for d in docs):
            return docs
        time.sleep(poll_interval)
    return None


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


# -------------------------------------------------
# Sidebar – document management
# -------------------------------------------------

st.sidebar.title("Documents")
st.sidebar.subheader("Add document")

uploaded = st.sidebar.file_uploader(
    "Upload policy PDF",
    type=["pdf"],
    accept_multiple_files=False,
)

if "needs_refresh" not in st.session_state:
    st.session_state.needs_refresh = True

if st.sidebar.button("Refresh documents"):
    st.session_state.needs_refresh = True
    st.rerun()

if uploaded is not None:
    if st.sidebar.button("Ingest document"):
        with st.spinner("Ingesting document..."):
            original_filename = uploaded.name

            with tempfile.TemporaryDirectory() as tmpdir:
                pdf_path = Path(tmpdir) / original_filename
                pdf_path.write_bytes(uploaded.getbuffer())

                event_id = asyncio.run(
                    send_event(
                        "rag/ingest_pdf",
                        {
                            "pdf_path": str(pdf_path.resolve()),
                            "original_filename": original_filename,
                            "policy_type": "policy_type",
                            "version": "version",
                            "jurisdiction": "jurisdiction",
                        },
                    )
                )

                output = wait_for_run_output(event_id)

        new_source_id = output.get("source_id")
        if not new_source_id:
            st.error("Ingest completed but no document ID was returned.")
            st.stop()

        with st.spinner("Finalizing document…"):
            docs = wait_for_document(new_source_id)

        if docs is None:
            st.error("Document was ingested but did not appear in time.")
            st.stop()

        st.success("Document ingested")
        st.session_state.docs = docs
        st.session_state.needs_refresh = False
        st.rerun()

if st.session_state.needs_refresh or not isinstance(st.session_state.get("docs"), list):
    st.session_state.docs = list_documents()
    st.session_state.needs_refresh = False

docs = st.session_state.docs

current_ids = {d["source_id"] for d in docs}

if "selected_docs" not in st.session_state:
    st.session_state.selected_docs = set(current_ids)
else:
    # add newly ingested docs
    st.session_state.selected_docs |= current_ids
    # remove deleted docs
    st.session_state.selected_docs &= current_ids

for doc in docs:
    sid = doc["source_id"]

    display_name = doc.get(
        "original_filename",
        os.path.basename(sid),
    )

    checked = sid in st.session_state.selected_docs
    new_checked = st.sidebar.checkbox(
        display_name,
        value=checked,
        key=f"chk_{sid}",
        help=f"{doc.get('policy_type', '')} | "
             f"v{doc.get('version', '')} | "
             f"{doc.get('jurisdiction', '')}",
    )

    if new_checked:
        st.session_state.selected_docs.add(sid)
    else:
        st.session_state.selected_docs.discard(sid)

    if st.sidebar.button("Delete", key=f"del_{sid}"):
        delete_document(sid)
        st.session_state.selected_docs.discard(sid)
        st.session_state.needs_refresh = True
        st.rerun()

st.sidebar.caption("Unchecked documents are excluded from search.")

# -------------------------------------------------
# Main – query
# -------------------------------------------------

st.title("Security Policy Q&A")

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
            display_name = s.get(
                "original_filename",
                os.path.basename(s.get("document", "")),
            )

            st.markdown(
                f"- **{display_name}**"
                f"{' | ' + s['policy_type'] if s.get('policy_type') else ''}"
                f"{' | v' + s['version'] if s.get('version') else ''}"
                f"{' | ' + s['jurisdiction'] if s.get('jurisdiction') else ''}"
            )

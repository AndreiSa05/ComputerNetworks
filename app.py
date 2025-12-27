import asyncio
from pathlib import Path
import time
import os
import requests

import streamlit as st
import inngest
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Security Policy RAG",
    page_icon="🔐",
    layout="centered",
)

# -------------------------------
# Inngest helpers
# -------------------------------

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


def wait_for_run_output(
    event_id: str,
    timeout_s: float = 120.0,
    poll_interval_s: float = 0.5,
) -> dict:
    start = time.time()
    last_status = None

    while True:
        runs = fetch_runs(event_id)
        if runs:
            run = runs[0]
            status = run.get("status")
            last_status = status or last_status

            if status in ("Completed", "Succeeded", "Success", "Finished"):
                return run.get("output") or {}

            if status in ("Failed", "Cancelled"):
                raise RuntimeError(f"Function run {status}")

        if time.time() - start > timeout_s:
            raise TimeoutError(
                f"Timed out waiting for run output (last status: {last_status})"
            )

        time.sleep(poll_interval_s)


# -------------------------------
# File handling
# -------------------------------

def save_uploaded_pdf(file) -> Path:
    uploads_dir = Path("uploads")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    file_path = uploads_dir / file.name
    file_path.write_bytes(file.getbuffer())
    return file_path


async def send_rag_ingest_event(
    pdf_path: Path,
    policy_type: str,
    version: str,
    jurisdiction: str,
):
    client = get_inngest_client()
    await client.send(
        inngest.Event(
            name="rag/ingest_pdf",
            data={
                "pdf_path": str(pdf_path.resolve()),
                "source_id": pdf_path.name,
                "policy_type": policy_type,
                "version": version,
                "jurisdiction": jurisdiction,
            },
        )
    )


async def send_rag_query_event(question: str, top_k: int) -> str:
    client = get_inngest_client()
    event_ids = await client.send(
        inngest.Event(
            name="rag/query_pdf_ai",
            data={
                "question": question,
                "top_k": top_k,
            },
        )
    )
    return event_ids[0]


# -------------------------------
# UI – Ingest
# -------------------------------

st.title("🔐 Security Policy RAG")

st.header("Ingest a policy document")

policy_type = st.text_input("Policy type", placeholder="Access Control")
version = st.text_input("Policy version", placeholder="2023.1")
jurisdiction = st.text_input("Jurisdiction", placeholder="EU")

uploaded = st.file_uploader(
    "Upload a policy PDF",
    type=["pdf"],
    accept_multiple_files=False,
)

if uploaded is not None:
    if st.button("Ingest policy"):
        with st.spinner("Uploading and ingesting policy..."):
            pdf_path = save_uploaded_pdf(uploaded)
            asyncio.run(
                send_rag_ingest_event(
                    pdf_path=pdf_path,
                    policy_type=policy_type,
                    version=version,
                    jurisdiction=jurisdiction,
                )
            )
            time.sleep(0.3)
        st.success(f"Ingestion triggered for: {pdf_path.name}")


st.divider()

# -------------------------------
# UI – Query
# -------------------------------

st.header("Ask a question")

with st.form("rag_query_form"):
    question = st.text_input("Your question")
    top_k = st.slider("Retrieval depth", 1, 10, 5)
    submitted = st.form_submit_button("Ask")

if submitted and question.strip():
    with st.spinner("Searching policies and generating answer..."):
        event_id = asyncio.run(
            send_rag_query_event(question.strip(), int(top_k))
        )
        output = wait_for_run_output(event_id)

    answer = output.get("answer", "")
    sources = output.get("sources", [])
    roles = output.get("roles", [])

    st.subheader("Answer")
    st.write(answer or "(No answer)")

    if roles:
        st.subheader("Responsible roles")
        for r in roles:
            st.write(f"- {r}")

    if sources:
        st.subheader("Sources")
        for s in sources:
            st.markdown(
                f"- **{os.path.basename(s.get('document',''))}**"
                f"{' | ' + s['policy_type'] if s.get('policy_type') else ''}"
                f"{' | v' + s['version'] if s.get('version') else ''}"
                f"{' | ' + s['jurisdiction'] if s.get('jurisdiction') else ''}"
            )

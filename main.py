import logging
from fastapi import FastAPI
import inngest
import inngest.fast_api
from inngest.experimental import ai
from dotenv import load_dotenv
import uuid
import os
import datetime
from custom_types import RAGQueryResult, RAGSearchResult, RAGChunkAndSrc, RAGUpsertResult
from data_loader import load_and_chunk_pdf, embed_texts, extract_roles
from vector_db import QdrantStorage

MAX_CONTEXT_CHARS = 3500

load_dotenv()

inngest_client = inngest.Inngest(
    app_id="policy",
    logger=logging.getLogger("uvicorn"),
    is_production=False,
    serializer=inngest.PydanticSerializer()
)


@inngest_client.create_function(
    fn_id="RAG: Ingest PDF",
    trigger=inngest.TriggerEvent(event="rag/ingest_pdf")
)
async def rag_ingest_pdf(ctx: inngest.Context):
    def _load(ctx: inngest.Context) -> RAGChunkAndSrc:
        pdf_path = ctx.event.data["pdf_path"]
        source_id = ctx.event.data.get("source_id", pdf_path)
        chunks = load_and_chunk_pdf(pdf_path)
        return RAGChunkAndSrc(chunks=chunks, source_id=source_id)

    def _upsert(chunks_and_src: RAGChunkAndSrc) -> RAGUpsertResult:
        chunks = chunks_and_src.chunks
        source_id = chunks_and_src.source_id
        vecs = embed_texts(chunks)
        ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source_id}:{i}")) for i in range(len(chunks))]
        payloads = [{
            "source": source_id,
            "text": chunks[i],
            "policy_type": ctx.event.data.get("policy_type", ""),
            "version": ctx.event.data.get("version", ""),
            "jurisdiction": ctx.event.data.get("jurisdiction", ""),
            "section": "",
            "roles": extract_roles(chunks[i]),
        } for i in range(len(chunks))]

        QdrantStorage().upsert(ids, vecs, payloads)
        return RAGUpsertResult(ingested=len(chunks))

    chunks_and_src = await ctx.step.run("load-and-chunk", lambda: _load(ctx), output_type=RAGChunkAndSrc)
    ingested = await ctx.step.run("embed-and-upsert", lambda: _upsert(chunks_and_src), output_type=RAGUpsertResult)
    return ingested.model_dump()


@inngest_client.create_function(
    fn_id="RAG: Query PDF",
    trigger=inngest.TriggerEvent(event="rag/query_pdf_ai")
)
async def rag_query_pdf_ai(ctx: inngest.Context):
    def _search(question: str, top_k: int = 5) -> RAGSearchResult:
        query_vec = embed_texts([question])[0]
        store = QdrantStorage()
        found = store.search(query_vec, top_k)
        return RAGSearchResult(contexts=found["contexts"], sources=found["sources"], roles=found["roles"])

    def select_context_chunks(chunks):
        total = 0
        selected = []
        for c in chunks:
            if total + len(c) > MAX_CONTEXT_CHARS:
                break
            selected.append(c)
            total += len(c)
        return selected

    question = ctx.event.data["question"]
    top_k = int(ctx.event.data.get("top_k", 5))

    found = await ctx.step.run("embed-and-search", lambda: _search(question, top_k), output_type=RAGSearchResult)

    if not found.contexts:
        return {
            "answer": (
                "I cannot answer this question based on the available "
                "security policy documents."
            ),
            "sources": [],
            "num_contexts": 0,
            "roles": 0,
        }

    selected_contexts = select_context_chunks(found.contexts)
    context_block = "\n\n".join(f"- {c}" for c in selected_contexts)

    print(context_block)

    user_content = (
        "Use the following context to answer the question.\n\n"
        f"Context:\n{context_block}\n\n"
        f"Question: {question}\n"
        "Answer concisely using the context above."
    )

    adapter = ai.openai.Adapter(
        auth_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o-mini"
    )

    res = await ctx.step.ai.infer(
        "llm-answer",
        adapter=adapter,
        body={
            "max_tokens": 1024,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a security policy assistant. "
                        "Answer ONLY using the provided policy context. "
                        "If the context does not contain the answer, say so explicitly. "
                        "Do not use outside knowledge."
                    )
                },
                {"role": "user", "content": user_content}
            ]
        }
    )

    answer = res["choices"][0]["message"]["content"].strip()
    return {
        "answer": answer,
        "sources": found.sources,
        "num_contexts": len(selected_contexts),
        "roles": getattr(found, "roles", []),
    }


app = FastAPI()

inngest.fast_api.serve(app, inngest_client, [rag_ingest_pdf, rag_query_pdf_ai])

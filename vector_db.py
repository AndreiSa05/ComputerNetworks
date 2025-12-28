from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct, Filter, FieldCondition, MatchValue, MatchAny


class QdrantStorage:
    def __init__(self, url="http://localhost:6333", collection="docs", dim=3072):
        self.client = QdrantClient(url=url, timeout=30)
        self.collection = collection
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

    def upsert(self, ids, vectors, payloads):
        points = [
            PointStruct(
                id=ids[i],
                vector=vectors[i],
                payload=payloads[i],
            )
            for i in range(len(ids))
        ]
        self.client.upsert(
            collection_name=self.collection,
            points=points,
            wait=True,
        )

    def search(self, query_vector, top_k: int = 5, min_score: float = 0.25, allowed_sources: list[str] | None = None,):
        if allowed_sources is not None and len(allowed_sources) == 0:
            return {
                "contexts": [],
                "sources": [],
                "roles": [],
            }

        query_filter = None
        if allowed_sources:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="source",
                        match=MatchAny(any=allowed_sources)
                    )
                ]
            )

        res = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            with_payload=True,
            limit=top_k,
            query_filter=query_filter,
        )

        contexts = []
        sources = []
        roles = set()

        for point in res.points:
            if point.score is None or point.score < min_score:
                continue

            payload = point.payload or {}
            text = payload.get("text", "")
            if not text:
                continue

            contexts.append(text)
            source = payload.get("source")
            if source:
                sources.append({
                    "document": source,
                    "section": payload.get("section", ""),
                    "policy_type": payload.get("policy_type", ""),
                    "version": payload.get("version", ""),
                    "jurisdiction": payload.get("jurisdiction", ""),
                })
            for r in payload.get("roles", []) or []:
                roles.add(r)

        if not contexts or not sources:
            return {
                "contexts": [],
                "sources": [],
                "roles": [],
            }

        unique_sources = {
            (s["document"], s["section"], s["version"]): s
            for s in sources
        }.values()

        return {
            "contexts": contexts,
            "sources": list(unique_sources),
            "roles": sorted(list(roles)),
        }

    def list_documents(self, limit: int = 10_000) -> list[dict]:
        documents = {}
        offset = None

        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection,
                with_payload=True,
                limit=1000,
                offset=offset,
            )

            for p in points:
                payload = p.payload or {}
                source = payload.get("source")
                if not source:
                    continue

                if source not in documents:
                    documents[source] = {
                        "source_id": source,
                        "policy_type": payload.get("policy_type", ""),
                        "version": payload.get("version", ""),
                        "jurisdiction": payload.get("jurisdiction", ""),
                        "chunks": 0,
                    }

                documents[source]["chunks"] += 1

            if offset is None:
                break

        return list(documents.values())

    def delete_document(self, source_id: str) -> int:

        points, _ = self.client.scroll(
            collection_name=self.collection,
            with_payload=False,
            limit=1,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="source",
                        match=MatchValue(value=source_id)
                    )
                ]
            ),
        )

        self.client.delete(
            collection_name=self.collection,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="source",
                        match=MatchValue(value=source_id)
                    )
                ]
            ),
            wait=True,
        )

        return len(points)

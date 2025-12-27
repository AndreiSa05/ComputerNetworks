import pydantic


class RAGChunkAndSrc(pydantic.BaseModel):
    chunks: list[str]
    source_id: str = None


class RAGUpsertResult(pydantic.BaseModel):
    ingested: int


class RAGSearchResult(pydantic.BaseModel):
    contexts: list[str]
    sources: list[dict]
    roles: list[str]


class RAGQueryResult(pydantic.BaseModel):
    answer: str
    sources: list[dict]
    num_contexts: int
    roles: list[str]

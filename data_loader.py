from openai import OpenAI
from llama_index.readers.file import PDFReader
from llama_index.core.node_parser import SentenceSplitter
from dotenv import load_dotenv
from pandas.core.window import doc

load_dotenv()

client=OpenAI()
EMBED_MODEL = "text-embedding-3-large"
EMBED_DIM = 3072

splitter = SentenceSplitter(chunk_size=1000, chunk_overlap=200)

def load_and_chunk_pdf(path: str):
    docs = PDFReader().load_data(file=path)
    texts = [doc.text for doc in docs if getattr(doc, "text", None)]
    chunks = []
    for text in texts:
        chunks.extend(splitter.split(text))
    return chunks

def embed_text(texts: list[str]) -> list[list[float]]:
    response=client.embeddings.create(
        model=EMBED_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]

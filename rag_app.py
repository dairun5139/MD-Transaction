"""
MMD Transaction RAG
"""
import os

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from pathlib import Path

from masker import mask_documents, MASK_CONFIG

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = BASE_DIR / "chroma_db"

EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
LLM_MODEL = "deepseek-r1:1.5b"

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
RETRIEVAL_K = 4

RAG_PROMPT = """\
Context:
{context}

Question: {question}

Answer:"""


# ======================== 1. Load ========================
def load_documents(data_dir):
    from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader

    docs = []
    for fp in sorted(data_dir.glob("*.pdf")):
        print(f"  [PDF] {fp.name}")
        docs.extend(PyPDFLoader(str(fp)).load())

    for fp in sorted(data_dir.glob("*.docx")):
        print(f"  [DOCX] {fp.name}")
        docs.extend(Docx2txtLoader(str(fp)).load())

    print(f"  loaded {len(docs)} pages/sections")
    return docs


# ======================== 2. Split ========================
def split_documents(docs):
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", ";", ",", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    print(f"  {len(chunks)} chunks")
    return chunks


# ======================== 3. Vectorstore ========================
def build_vectorstore(chunks):
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_chroma import Chroma

    print(f"  embedding model: {EMBED_MODEL}")
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBED_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

    print(f"  building ChromaDB -> {CHROMA_DIR}")
    vs = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(CHROMA_DIR),
    )
    return vs


def load_vectorstore():
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_chroma import Chroma

    if not (CHROMA_DIR / "chroma.sqlite3").exists():
        return None

    embeddings = HuggingFaceEmbeddings(
        model_name=EMBED_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
    return Chroma(
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
    )


# ======================== 4. Ask ========================
def ask(vectorstore, question):
    import requests

    docs = vectorstore.similarity_search(question, k=RETRIEVAL_K)
    context = "\n\n---\n\n".join(d.page_content for d in docs)
    prompt_text = RAG_PROMPT.format(context=context, question=question)

    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": LLM_MODEL, "prompt": prompt_text, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except requests.ConnectionError:
        return "[ERROR] 无法连接 Ollama，请先运行: ollama serve"
    except requests.Timeout:
        return "[ERROR] 模型推理超时，请检查 Ollama 是否正常运行"


# ======================== 5. CLI ========================
def interactive_qa(vectorstore):
    print()
    print("=" * 56)
    print(f"  MMD Transaction RAG  |  model: {LLM_MODEL}  |  top-k: {RETRIEVAL_K}")
    print("  type 'quit' to exit")
    print("=" * 56)
    print()

    while True:
        try:
            q = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  bye.")
            break

        if not q:
            continue
        if q.lower() in ("quit", "exit", "q"):
            print("  bye.")
            break

        print("  ...\n")
        try:
            ans = ask(vectorstore, q)
            print(ans)
            print()
        except Exception:
            import traceback
            print("-" * 40)
            traceback.print_exc()
            print("-" * 40)
            print()


# ======================== main ========================
def main():
    print("=" * 56)
    print("  MMD Transaction - RAG Knowledge Base")
    print("=" * 56)

    vs = load_vectorstore()
    if vs is not None:
        print("\n  Using cached vectorstore. Delete chroma_db/ to re-index.\n")
    else:
        print("\n[1/3] Loading documents...")
        docs = load_documents(DATA_DIR)
        if not docs:
            print("ERROR: no documents found in data/")
            return

        print("\n[*] Masking sensitive data...")
        docs = mask_documents(docs, config=MASK_CONFIG)

        print("\n[2/3] Splitting...")
        chunks = split_documents(docs)

        print("\n[3/3] Building vectorstore...")
        vs = build_vectorstore(chunks)
        print("  done.\n")

    print("[OK] Ready.\n")
    interactive_qa(vs)


if __name__ == "__main__":
    main()

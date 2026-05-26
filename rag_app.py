"""
MMD Transaction RAG — 改进版

改进点：
1. 默认使用 FAISS 本地向量库，规避 Windows 上 ChromaDB 1.x 查询崩溃风险。
2. 保留 ChromaDB 作为可选后端：设置环境变量 RAG_VECTOR_BACKEND=chroma。
3. 每个 chunk 增加 chunk_id、filename、page_label、chunk_index、text_hash 等元数据。
4. 问答输出答案 + 参考片段，方便定位原文来源。
5. 写入 logs/rag_trace.jsonl，便于排查召回质量。
6. Prompt 增加“只基于证据回答、证据不足则说明”的约束。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

from masker import MASK_CONFIG, mask_documents

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = BASE_DIR / "chroma_db"
FAISS_DIR = BASE_DIR / "faiss_index"
LOG_DIR = BASE_DIR / "logs"
TRACE_FILE = LOG_DIR / "rag_trace.jsonl"

LLM_MODEL = os.getenv("RAG_LLM_MODEL", "deepseek-r1:1.5b")
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "nomic-embed-text")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# 推荐默认用 FAISS，规避 Windows + ChromaDB 1.x 的底层崩溃风险。
# 如需继续使用 ChromaDB：PowerShell 中执行 $env:RAG_VECTOR_BACKEND="chroma"
VECTOR_BACKEND = os.getenv("RAG_VECTOR_BACKEND", "faiss").lower().strip()

CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "650"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "100"))
RETRIEVAL_K = int(os.getenv("RAG_RETRIEVAL_K", "6"))

PROMPT_VERSION = "rag_prompt_v2_evidence_zh"
INGEST_VERSION = "2026-05-25-v2"


# ======================== Retrieval Balance Config ========================
# 先扩大候选召回，再做文档均衡，避免 700 页大 PDF 占满全部 top-k
CANDIDATE_K = 120
MAX_CHUNKS_PER_SOURCE = 5
# 文档权重：短文档/规则汇编更适合作为问答依据，给予轻微加权
# FAISS 分数通常是距离，越小越相似；后续用 score / weight 调整排序
DOC_WEIGHTS = {
    "蒙东新能源电站交易规则汇编_AI算法开发版.docx": 1.40,
    "蒙东电力交易市场交易员培训教材.pdf": 1.25,
    "20251021010756789.pdf": 1.00,
}

RETRIEVAL_K = 10
RAG_PROMPT = """\
你是“蒙东新能源电站交易规则”本地知识库问答助手。

回答规则：
1. 只能依据【参考片段】回答，不得编造未出现在片段中的规则、数值或流程。
2. 涉及规则、时间、价格、电量、结算、主体条件时，必须在句末标注来源编号，如 [S1]、[S2]。
3. 如果参考片段不足以回答，请明确说：“当前知识库未检索到足够依据”，并说明还需要查哪类文件。
4. 不要输出思考过程，不要输出与问题无关的背景。
5. 优先使用中文，表达要适合电力交易员阅读。

【参考片段】
{context}

【用户问题】
{question}

请按以下格式回答：
一、结论
二、依据
三、注意事项
"""


# ======================== 0. Ollama Embeddings ========================
class OllamaEmbeddings:
    """
    用 Ollama HTTP API 做文本向量化，完全绕开 PyTorch / sentence-transformers。
    需要本地已拉取：ollama pull nomic-embed-text
    """

    def __init__(self, model: str = EMBED_MODEL, base_url: str = OLLAMA_BASE_URL):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def _embed(self, texts: List[str]) -> List[List[float]]:
        vectors = []
        for text in texts:
            resp = requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=60,
            )
            resp.raise_for_status()
            vectors.append(resp.json()["embedding"])
        return vectors

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        print(f"  encoding {len(texts)} texts via Ollama ({self.model})...")
        return self._embed(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._embed([text])[0]

    def __call__(self, text: str) -> List[float]:
        return self.embed_query(text)


# ======================== 1. Load ========================
def load_documents(data_dir: Path):
    from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader

    docs = []
    if not data_dir.exists():
        print(f"ERROR: data directory not found: {data_dir}")
        return docs

    for fp in sorted(data_dir.glob("*.pdf")):
        print(f"  [PDF] {fp.name}")
        loaded = PyPDFLoader(str(fp)).load()
        for d in loaded:
            d.metadata["filename"] = fp.name
            d.metadata["doc_type"] = "pdf"
        docs.extend(loaded)

    for fp in sorted(data_dir.glob("*.docx")):
        print(f"  [DOCX] {fp.name}")
        loaded = Docx2txtLoader(str(fp)).load()
        for d in loaded:
            d.metadata["filename"] = fp.name
            d.metadata["doc_type"] = "docx"
        docs.extend(loaded)

    print(f"  loaded {len(docs)} pages/sections")
    return docs


# ======================== 2. Split + Metadata ========================
def _safe_slug(text: str) -> str:
    stem = Path(text).stem if text else "doc"
    keep = []
    for ch in stem:
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff":
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep).strip("_")[:40] or "doc"


def _hash_text(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()[:8]


def _guess_section_title(text: str) -> str:
    """粗略提取章/节/条标题，便于召回展示；不影响检索。"""
    for raw in text.splitlines()[:8]:
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("第", "第一", "第二", "第三", "第四", "第五", "第六", "第七", "第八", "第九", "第十")):
            if any(key in line for key in ("章", "节", "条", "章 ", "节 ")) and len(line) <= 80:
                return line
        if len(line) <= 40 and any(key in line for key in ("市场", "交易", "结算", "注册", "申报", "价格", "保量")):
            return line
    return ""


def enrich_chunk_metadata(chunks):
    counters: Dict[str, int] = {}
    for chunk in chunks:
        meta = chunk.metadata or {}
        source = meta.get("source", "unknown")
        filename = meta.get("filename") or Path(source).name
        doc_id = _safe_slug(filename)
        page = meta.get("page", "")
        page_label = str(meta.get("page_label") or (page + 1 if isinstance(page, int) else page or ""))

        key = f"{doc_id}_p{page_label}"
        counters[key] = counters.get(key, 0) + 1
        chunk_index = counters[key]
        text_hash = _hash_text(chunk.page_content)
        chunk_id = f"{doc_id}_p{page_label}_{chunk_index:03d}_{text_hash}"

        meta.update(
            {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "filename": filename,
                "source": source,
                "page_label": page_label,
                "section_title": _guess_section_title(chunk.page_content),
                "chunk_index": chunk_index,
                "text_hash": text_hash,
                "masked": True,
                "mask_policy": "business_numbers_preserved_v2",
                "ingest_version": INGEST_VERSION,
            }
        )
        chunk.metadata = meta
    return chunks


def split_documents(docs):
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=[
            "\n第", "\n\n", "\n",
            "。", "；", "，", "：",
            ".", ";", ",", " ", "",
        ],
    )
    chunks = splitter.split_documents(docs)
    chunks = enrich_chunk_metadata(chunks)
    print(f"  {len(chunks)} chunks")
    return chunks


# ======================== 3. Vectorstore ========================
def build_faiss_vectorstore(chunks):
    from langchain_community.vectorstores import FAISS

    embeddings = OllamaEmbeddings()
    print(f"  embedding via Ollama: {EMBED_MODEL}")
    print(f"  building FAISS -> {FAISS_DIR}")
    vs = FAISS.from_documents(chunks, embeddings)
    if FAISS_DIR.exists():
        shutil.rmtree(FAISS_DIR)
    vs.save_local(str(FAISS_DIR))
    return vs


def load_faiss_vectorstore():
    from langchain_community.vectorstores import FAISS

    index_file = FAISS_DIR / "index.faiss"
    pkl_file = FAISS_DIR / "index.pkl"
    if not index_file.exists() or not pkl_file.exists():
        return None
    embeddings = OllamaEmbeddings()
    return FAISS.load_local(
        str(FAISS_DIR),
        embeddings,
        allow_dangerous_deserialization=True,
    )


def build_chroma_vectorstore(chunks):
    from langchain_chroma import Chroma

    embeddings = OllamaEmbeddings()
    print(f"  embedding via Ollama: {EMBED_MODEL}")
    print(f"  building ChromaDB -> {CHROMA_DIR}")
    return Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(CHROMA_DIR),
    )


def load_chroma_vectorstore():
    from langchain_chroma import Chroma

    if not (CHROMA_DIR / "chroma.sqlite3").exists():
        return None
    embeddings = OllamaEmbeddings()
    return Chroma(
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
    )


def build_vectorstore(chunks):
    if VECTOR_BACKEND == "chroma":
        return build_chroma_vectorstore(chunks)
    return build_faiss_vectorstore(chunks)


def load_vectorstore():
    if VECTOR_BACKEND == "chroma":
        return load_chroma_vectorstore()
    return load_faiss_vectorstore()


# ======================== 4. Ask + Sources + Trace ========================
def _short_excerpt(text: str, limit: int = 260) -> str:
    text = " ".join((text or "").split())
    return text[:limit] + ("..." if len(text) > limit else "")


def _format_context(results: List[Tuple[Any, float]]) -> Tuple[str, List[Dict[str, Any]]]:
    context_blocks = []
    sources = []

    for rank, (doc, score) in enumerate(results, start=1):
        meta = doc.metadata or {}
        sid = f"S{rank}"
        filename = meta.get("filename") or Path(meta.get("source", "unknown")).name
        page_label = meta.get("page_label") or meta.get("page") or ""
        section_title = meta.get("section_title") or ""
        chunk_id = meta.get("chunk_id") or f"chunk_{rank}"
        excerpt = _short_excerpt(doc.page_content)

        sources.append(
            {
                "id": sid,
                "rank": rank,
                "score": float(score) if score is not None else None,
                "filename": filename,
                "source": meta.get("source", "unknown"),
                "page_label": page_label,
                "section_title": section_title,
                "chunk_id": chunk_id,
                "excerpt": excerpt,
            }
        )

        context_blocks.append(
            f"[{sid}] 文件：{filename} | 页码/段落：{page_label} | 章节：{section_title} | chunk_id：{chunk_id}\n"
            f"{doc.page_content}"
        )

    return "\n\n---\n\n".join(context_blocks), sources


def _retrieve(vectorstore, question: str):
    """兼容 FAISS / Chroma：优先返回带分数的检索结果。"""
    if hasattr(vectorstore, "similarity_search_with_score"):
        return vectorstore.similarity_search_with_score(question, k=RETRIEVAL_K)
    docs = vectorstore.similarity_search(question, k=RETRIEVAL_K)
    return [(d, None) for d in docs]


def _call_ollama(prompt_text: str) -> str:
    resp = requests.post(
        f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate",
        json={
            "model": LLM_MODEL,
            "prompt": prompt_text,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
                "num_ctx": 8192,
            },
        },
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def _write_trace(record: Dict[str, Any]):
    LOG_DIR.mkdir(exist_ok=True)
    with TRACE_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _retrieve(vectorstore, question):
    """
    文档均衡检索：
    先召回更多候选片段，再按文档权重和每文档数量上限筛选。
    避免 20251021010756789.pdf 因页数过多而占满全部上下文。
    """
    candidate_k = max(CANDIDATE_K, RETRIEVAL_K)

    raw_results = vectorstore.similarity_search_with_score(
        question,
        k=candidate_k,
    )

    def _source_name(doc):
        meta = doc.metadata or {}
        src = meta.get("source") or meta.get("filename") or "unknown"
        src = str(src)
        try:
            return Path(src).name
        except Exception:
            return src

    def _weight_for_source(source_name):
        for key, weight in DOC_WEIGHTS.items():
            if key in source_name:
                return float(weight)
        return 1.0

    ranked = []
    for doc, score in raw_results:
        source_name = _source_name(doc)
        weight = _weight_for_source(source_name)

        try:
            numeric_score = float(score)
        except Exception:
            numeric_score = 999999.0

        # FAISS 分数通常是距离，越小越相似。
        # 高权重文档除以 weight，使其排序更靠前。
        adjusted_score = numeric_score / max(weight, 0.01)

        ranked.append({
            "doc": doc,
            "score": score,
            "source": source_name,
            "adjusted_score": adjusted_score,
        })

    ranked.sort(key=lambda x: x["adjusted_score"])

    selected = []
    source_counts = {}

    # 第一轮：每个文档最多保留 MAX_CHUNKS_PER_SOURCE 个
    for item in ranked:
        src = item["source"]
        if source_counts.get(src, 0) >= MAX_CHUNKS_PER_SOURCE:
            continue

        selected.append((item["doc"], item["score"]))
        source_counts[src] = source_counts.get(src, 0) + 1

        if len(selected) >= RETRIEVAL_K:
            break

    # 第二轮：如果不够 top-k，则放宽限制补齐
    if len(selected) < RETRIEVAL_K:
        selected_ids = {id(doc) for doc, _ in selected}

        for item in ranked:
            doc = item["doc"]
            if id(doc) in selected_ids:
                continue

            selected.append((doc, item["score"]))
            selected_ids.add(id(doc))

            if len(selected) >= RETRIEVAL_K:
                break

    # 打印召回来源分布
    try:
        dist = {}
        for doc, _ in selected:
            src = _source_name(doc)
            dist[src] = dist.get(src, 0) + 1

        print("  召回来源分布: " + " | ".join(f"{k}: {v}" for k, v in dist.items()))
    except Exception:
        pass

    return selected


def ask(vectorstore, question: str) -> Dict[str, Any]:
    results = _retrieve(vectorstore, question)
    context, sources = _format_context(results)
    prompt_text = RAG_PROMPT.format(context=context, question=question)

    try:
        answer = _call_ollama(prompt_text)
    except requests.ConnectionError:
        answer = "[ERROR] 无法连接 Ollama，请先运行: ollama serve"
    except requests.Timeout:
        answer = "[ERROR] 模型推理超时，请检查 Ollama 是否正常运行，或换用更小 top-k。"
    except requests.HTTPError as e:
        answer = f"[ERROR] Ollama HTTP 调用失败：{e}"

    result = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "answer": answer,
        "sources": sources,
        "model": LLM_MODEL,
        "embed_model": EMBED_MODEL,
        "vector_backend": VECTOR_BACKEND,
        "retrieval_k": RETRIEVAL_K,
        "prompt_version": PROMPT_VERSION,
    }
    _write_trace(result)
    return result


def print_answer(result: Dict[str, Any]):
    print(result["answer"])
    print()
    print("参考片段：")
    for s in result.get("sources", []):
        score_text = f"score={s['score']:.4f}" if isinstance(s.get("score"), float) else "score=N/A"
        loc = f"p.{s['page_label']}" if s.get("page_label") not in (None, "") else "p.N/A"
        section = f" | {s['section_title']}" if s.get("section_title") else ""
        print(f"[{s['id']}] {s['filename']} | {loc} | {score_text}{section}")
        print(f"    chunk_id={s['chunk_id']}")
        print(f"    摘录：{s['excerpt']}")
    print(f"\n[trace] {TRACE_FILE}")


# ======================== 5. CLI ========================
def interactive_qa(vectorstore):
    print()
    print("=" * 72)
    print(f"  MMD Transaction RAG | backend: {VECTOR_BACKEND} | model: {LLM_MODEL} | top-k: {RETRIEVAL_K}")
    print("  输入问题直接回车；输入 quit / exit / q 退出")
    print("=" * 72)
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

        print("  检索并生成中...\n")
        try:
            result = ask(vectorstore, q)
            print_answer(result)
            print()
        except Exception:
            import traceback
            print("-" * 40)
            traceback.print_exc()
            print("-" * 40)
            print()


# ======================== main ========================
def main():
    print("=" * 72)
    print("  MMD Transaction - RAG Knowledge Base")
    print("=" * 72)

    vs = load_vectorstore()
    if vs is not None:
        index_dir = CHROMA_DIR if VECTOR_BACKEND == "chroma" else FAISS_DIR
        print(f"\n  Using cached vectorstore: {index_dir}")
        print("  如修改了知识源或脱敏配置，请删除索引目录后重建。\n")
    else:
        print("\n[1/3] Loading documents...")
        docs = load_documents(DATA_DIR)
        if not docs:
            print("ERROR: no documents found in data/")
            return

        print("\n[*] Masking sensitive data...")
        docs = mask_documents(docs, config=MASK_CONFIG)

        print("\n[2/3] Splitting and enriching metadata...")
        chunks = split_documents(docs)

        print("\n[3/3] Building vectorstore...")
        vs = build_vectorstore(chunks)
        print("  done.\n")

    print("[OK] Ready.\n")
    interactive_qa(vs)


if __name__ == "__main__":
    main()

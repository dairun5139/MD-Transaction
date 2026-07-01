"""
FastAPI service for the MD Transaction RAG knowledge base.

一键启动（推荐）：
    python api_app.py

高级启动（手动控制参数）：
    uvicorn api_app:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import rag_app


# ---- 向量库预加载（lifespan 依赖，须在 app 创建之前定义） ----
WEB_INDEX = Path(__file__).parent / "web" / "index.html"
_VECTORSTORE = None
_VECTORSTORE_LOCK = threading.Lock()


def _preload_vectorstore():
    """尝试在服务启动时预加载 FAISS 索引；加载失败不阻断服务启动（交由首次请求报错）。"""
    global _VECTORSTORE
    try:
        vs = rag_app.load_vectorstore()
        if vs is not None:
            with _VECTORSTORE_LOCK:
                _VECTORSTORE = vs
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务启动时异步预加载向量库，避免第一个请求阻塞等待。"""
    try:
        await asyncio.to_thread(_preload_vectorstore)
    except Exception:
        pass
    yield


# ---- FastAPI 应用 ----
app = FastAPI(
    title="MD Transaction RAG API",
    description="Local RAG question-answering service for Mongdong power trading documents.",
    version="0.1.0",
    lifespan=lifespan,
)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000, description="用户问题")


class SourceItem(BaseModel):
    id: str
    rank: int
    score: Optional[float] = None
    filename: str
    source: str
    page_label: Any = ""
    section_title: str = ""
    location_text: str = ""
    chunk_id: str
    excerpt: str


class AskResponse(BaseModel):
    ts: str
    question: str
    answer: str
    sources: List[SourceItem]
    model: str
    embed_model: str
    vector_backend: str
    retrieval_k: int
    candidate_k: int
    max_chunks_per_source: int
    prompt_version: str


def _index_dir() -> Path:
    return rag_app.FAISS_DIR


def _load_manifest() -> Optional[Dict[str, Any]]:
    manifest = _index_dir() / rag_app.MANIFEST_NAME
    if not manifest.exists():
        return None
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return None


@lru_cache(maxsize=1)
def _load_home_page() -> str:
    try:
        return WEB_INDEX.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Web 页面文件不存在：{WEB_INDEX}") from exc


def get_vectorstore():
    global _VECTORSTORE
    if _VECTORSTORE is not None:
        return _VECTORSTORE
    with _VECTORSTORE_LOCK:
        if _VECTORSTORE is None:
            _VECTORSTORE = rag_app.load_vectorstore()
        if _VECTORSTORE is None:
            raise HTTPException(
                status_code=503,
                detail="向量索引不存在，请运行 python api_app.py 自动构建索引。",
            )
    return _VECTORSTORE


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return _load_home_page()


@app.get("/api/health")
def health() -> Dict[str, Any]:
    index_dir = _index_dir()
    ollama_ok = False
    try:
        resp = requests.get(f"{rag_app.OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=3)
        ollama_ok = resp.ok
    except requests.RequestException:
        ollama_ok = False
    return {
        "status": "ok" if index_dir.exists() and ollama_ok else "degraded",
        "ts": datetime.now().isoformat(timespec="seconds"),
        "vector_backend": rag_app.VECTOR_BACKEND,
        "index_dir": str(index_dir),
        "index_exists": index_dir.exists(),
        "manifest_exists": (index_dir / rag_app.MANIFEST_NAME).exists(),
        "ollama_ok": ollama_ok,
        "model": rag_app.LLM_MODEL,
        "embed_model": rag_app.EMBED_MODEL,
    }


@app.get("/api/index/status")
def index_status() -> Dict[str, Any]:
    index_dir = _index_dir()
    files = []
    if index_dir.exists():
        files = [
            {
                "name": item.name,
                "size": item.stat().st_size,
                "mtime": datetime.fromtimestamp(item.stat().st_mtime).isoformat(timespec="seconds"),
            }
            for item in sorted(index_dir.glob("*"))
            if item.is_file()
        ]
    return {
        "vector_backend": rag_app.VECTOR_BACKEND,
        "index_dir": str(index_dir),
        "index_exists": index_dir.exists(),
        "files": files,
        "manifest": _load_manifest(),
        "retrieval": {
            "retrieval_k": rag_app.RETRIEVAL_K,
            "candidate_k": rag_app.CANDIDATE_K,
            "max_chunks_per_source": rag_app.MAX_CHUNKS_PER_SOURCE,
        },
    }


@app.post("/api/ask", response_model=AskResponse)
def ask(req: AskRequest) -> Dict[str, Any]:
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="问题不能为空。")
    try:
        return rag_app.ask(get_vectorstore(), question)
    except HTTPException:
        raise
    except requests.ConnectionError as exc:
        raise HTTPException(status_code=503, detail="无法连接 Ollama，请确认 ollama serve 已启动。") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"问答服务异常：{exc}") from exc


# ======================== 一键启动入口 ========================
if __name__ == "__main__":
    import sys
    import uvicorn
    import webbrowser

    host = "127.0.0.1"
    port = 8000
    url = f"http://{host}:{port}/"

    print("=" * 64)
    print("  MD Transaction RAG — 一键启动")
    print("=" * 64)
    print()

    # ---- 1. 索引检测与自动构建 ----
    index_faiss = rag_app.FAISS_DIR / "index.faiss"
    index_pkl = rag_app.FAISS_DIR / "index.pkl"

    if index_faiss.exists() and index_pkl.exists():
        print("  FAISS 索引已存在，跳过构建。")
        print("  （如需重建，请删除 faiss_index/ 目录后重新运行）\n")
    else:
        print("[1/3] FAISS 索引不存在，自动构建...")
        print(f"  知识源目录: {rag_app.DATA_DIR}")
        docs = rag_app.load_documents(rag_app.DATA_DIR)
        if not docs:
            print(f"\n  ERROR: data/ 目录下未找到 PDF/DOCX 文件。")
            print(f"  请将知识源文件放入 {rag_app.DATA_DIR} 后重试。")
            sys.exit(1)
        print(f"  已加载 {len(docs)} 页/段落")

        print("\n[*] 清洗提取文本...")
        docs = rag_app.clean_documents(docs)

        print("\n[*] 过滤封面、目录等低价值页面...")
        docs = rag_app.filter_documents(docs)

        print("\n[*] 数据脱敏（保留业务数字）...")
        from masker import mask_documents, MASK_CONFIG
        docs = mask_documents(docs, config=MASK_CONFIG)

        print("\n[2/3] 切片并构建 FAISS 索引...")
        chunks = rag_app.split_documents(docs)
        vs = rag_app.build_vectorstore(chunks)
        print(f"\n[3/3] 索引构建完成，共 {len(chunks)} 个 chunk\n")

    # ---- 2. 预加载向量库 ----
    print("  预加载向量库...")
    _preload_vectorstore()
    print("  完成。\n")

    # ---- 3. 自动打开浏览器 ----
    def _open_browser():
        import time as _time
        _time.sleep(1.5)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_open_browser, daemon=True).start()

    # ---- 4. 启动服务 ----
    print(f"  启动服务 → {url}")
    print("  按 Ctrl+C 停止服务")
    print("=" * 64)
    uvicorn.run(app, host=host, port=port, log_level="info")

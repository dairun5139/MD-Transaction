"""环境检查 — 验证 MMD Transaction RAG 依赖和 Ollama 服务。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHECKS = []


def check(label: str, import_name: str, pkg: str | None = None):
    try:
        __import__(import_name)
        CHECKS.append((label, "OK", ""))
    except ImportError:
        CHECKS.append((label, "MISSING", f"pip install {pkg or import_name}"))


# Python
if sys.version_info >= (3, 10):
    CHECKS.append(("Python 3.10+", "OK", sys.version.split()[0]))
else:
    CHECKS.append(("Python 3.10+", "FAIL", f"当前版本 {sys.version.split()[0]}，请升级"))

# Core dependencies used by the improved main chain.
check("langchain", "langchain")
check("langchain_community", "langchain_community", "langchain-community")
check("langchain_text_splitters", "langchain_text_splitters", "langchain-text-splitters")
check("faiss", "faiss", "faiss-cpu")
check("langchain_chroma", "langchain_chroma", "langchain-chroma")
check("chromadb", "chromadb")
check("requests", "requests")
check("pypdf", "pypdf")
check("docx2txt", "docx2txt")
check("dotenv", "dotenv", "python-dotenv")
check("jieba", "jieba")
check("rank_bm25", "rank_bm25", "rank-bm25")

# Ollama checks should be quick and should not block too long.
try:
    r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=8)
    out = r.stdout.lower()
    if "deepseek-r1" in out:
        CHECKS.append(("Ollama deepseek-r1", "OK", ""))
    else:
        CHECKS.append(("Ollama deepseek-r1", "WARN", "未找到 deepseek-r1，请运行: ollama pull deepseek-r1:1.5b"))
    if "nomic-embed-text" in out:
        CHECKS.append(("Ollama nomic-embed-text", "OK", ""))
    else:
        CHECKS.append(("Ollama nomic-embed-text", "WARN", "未找到嵌入模型，请运行: ollama pull nomic-embed-text"))
except FileNotFoundError:
    CHECKS.append(("Ollama", "MISSING", "ollama 未安装或未加入 PATH"))
except subprocess.TimeoutExpired:
    CHECKS.append(("Ollama", "WARN", "ollama list 超时，请确认 Ollama 服务是否正常"))
except Exception as e:
    CHECKS.append(("Ollama", "WARN", f"Ollama 检查失败：{e}"))

# Knowledge source files.
data = Path(__file__).parent / "data"
files = list(data.glob("*")) if data.exists() else []
pdfs = [f for f in files if f.suffix.lower() == ".pdf"]
docxs = [f for f in files if f.suffix.lower() == ".docx"]
CHECKS.append(("知识源文件", "OK" if files else "EMPTY", f"PDF: {len(pdfs)}, DOCX: {len(docxs)}" if files else "data/ 目录为空，请放入文档"))

# Output.
print("=" * 64)
print("  MMD Transaction — 环境检查")
print("=" * 64)
for label, status, detail in CHECKS:
    icon = {"OK": "[OK]", "WARN": "[WARN]", "MISSING": "[MISS]", "FAIL": "[FAIL]", "EMPTY": "[EMPTY]"}[status]
    line = f"  {icon} {label}"
    if detail:
        line += f"  — {detail}"
    print(line)

fail = sum(1 for _, s, _ in CHECKS if s in ("MISSING", "FAIL"))
warn = sum(1 for _, s, _ in CHECKS if s in ("WARN", "EMPTY"))
print("=" * 64)
if fail:
    print(f"  共 {fail} 项缺失，请先修复后再运行 rag_app.py")
elif warn:
    print(f"  基础依赖通过，但有 {warn} 项提醒；如模型未拉取，请先执行 ollama pull。")
else:
    print("  所有检查通过，可以运行: python rag_app.py")

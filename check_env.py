"""环境检查 — 验证 MD Transaction RAG 依赖和 Ollama 服务。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHECKS = []


def add_check(label: str, status: str, detail: str = "", required: bool = True):
    CHECKS.append((label, status, detail, required))


def check(label: str, import_name: str, pkg: str | None = None, required: bool = True):
    try:
        __import__(import_name)
        add_check(label, "OK", "", required)
    except ImportError:
        status = "MISSING" if required else "OPTIONAL"
        add_check(label, status, f"pip install {pkg or import_name}", required)


# Python
if sys.version_info >= (3, 10):
    add_check("Python 3.10+", "OK", sys.version.split()[0])
else:
    add_check("Python 3.10+", "FAIL", f"当前版本 {sys.version.split()[0]}，请升级")

add_check("Python executable", "OK", sys.executable)

# Core dependencies used by the FAISS main chain.
check("langchain", "langchain")
check("langchain_community", "langchain_community", "langchain-community")
check("langchain_text_splitters", "langchain_text_splitters", "langchain-text-splitters")
check("requests", "requests")
check("pypdf", "pypdf")
check("docx2txt", "docx2txt")
check("fastapi", "fastapi")
check("uvicorn", "uvicorn")
check("faiss", "faiss", "faiss-cpu")

# Ollama checks should be quick and should not block too long.
try:
    r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=8)
    out = r.stdout.lower()
    if "qwen2.5" in out:
        add_check("Ollama qwen2.5", "OK")
    else:
        add_check("Ollama qwen2.5", "WARN", "未找到 qwen2.5，请运行: ollama pull qwen2.5:7b")
    if "nomic-embed-text" in out:
        add_check("Ollama nomic-embed-text", "OK")
    else:
        add_check("Ollama nomic-embed-text", "WARN", "未找到嵌入模型，请运行: ollama pull nomic-embed-text")
except FileNotFoundError:
    add_check("Ollama", "MISSING", "ollama 未安装或未加入 PATH")
except subprocess.TimeoutExpired:
    add_check("Ollama", "WARN", "ollama list 超时，请确认 Ollama 服务是否正常")
except Exception as e:
    add_check("Ollama", "WARN", f"Ollama 检查失败：{e}")

# Knowledge source files.
data = Path(__file__).parent / "data"
files = list(data.glob("*")) if data.exists() else []
pdfs = [f for f in files if f.suffix.lower() == ".pdf"]
docxs = [f for f in files if f.suffix.lower() == ".docx"]
add_check("知识源文件", "OK" if files else "EMPTY", f"PDF: {len(pdfs)}, DOCX: {len(docxs)}" if files else "data/ 目录为空，请放入文档")

# Output.
print("=" * 64)
print("  MD Transaction — 环境检查")
print("  vector backend: faiss")
print("=" * 64)
for label, status, detail, required in CHECKS:
    icon = {
        "OK": "[OK]",
        "WARN": "[WARN]",
        "MISSING": "[MISS]",
        "OPTIONAL": "[OPT]",
        "FAIL": "[FAIL]",
        "EMPTY": "[EMPTY]",
    }[status]
    line = f"  {icon} {label}"
    if detail:
        line += f"  — {detail}"
    if not required and status != "OK":
        line += "（可选）"
    print(line)

fail = sum(1 for _, s, _, required in CHECKS if required and s in ("MISSING", "FAIL"))
warn = sum(1 for _, s, _, _ in CHECKS if s in ("WARN", "EMPTY", "OPTIONAL"))
print("=" * 64)
if fail:
    print(f"  当前解释器下有 {fail} 项核心依赖缺失；如在 PyCharm 中运行，请确认使用的是项目虚拟环境。")
elif warn:
    print(f"  核心依赖通过，但有 {warn} 项提醒。")
else:
    print("  所有检查通过，可以运行: python rag_app.py")

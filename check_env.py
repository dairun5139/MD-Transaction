"""环境检查 — 验证 RAG 依赖是否正确安装"""
import sys

CHECKS = []

def check(label, import_name, pkg=None):
    try:
        __import__(import_name)
        CHECKS.append((label, "OK", ""))
    except ImportError:
        CHECKS.append((label, "MISSING", f"pip install {pkg or import_name}"))

check("Python 3.10+", "sys")
if sys.version_info < (3, 10):
    CHECKS[-1] = ("Python 3.10+", "FAIL", f"当前版本 {sys.version.split()[0]}，请升级")

check("langchain", "langchain")
check("langchain_community", "langchain_community")
check("langchain_ollama", "langchain_ollama")
check("langchain_chroma", "langchain_chroma")
check("langchain_huggingface", "langchain_huggingface")
check("sentence_transformers", "sentence_transformers")
check("chromadb", "chromadb")
check("pypdf", "pypdf")
check("docx2txt", "docx2txt")
check("dotenv", "dotenv")

# Ollama 检查
import subprocess
try:
    r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
    if "deepseek-r1" in r.stdout:
        CHECKS.append(("Ollama deepseek-r1", "OK", ""))
    else:
        CHECKS.append(("Ollama deepseek-r1", "WARN", "未找到 deepseek-r1 模型，请先运行: ollama pull deepseek-r1"))
except FileNotFoundError:
    CHECKS.append(("Ollama", "MISSING", "ollama 未安装或未加入 PATH"))
except Exception:
    CHECKS.append(("Ollama", "WARN", "Ollama 未运行，请确保已启动"))

# 知识源检查
from pathlib import Path
data = Path(__file__).parent / "data"
files = list(data.glob("*")) if data.exists() else []
pdfs = [f for f in files if f.suffix == ".pdf"]
docxs = [f for f in files if f.suffix == ".docx"]
CHECKS.append(("知识源文件", "OK" if files else "EMPTY",
              f"PDF: {len(pdfs)}, DOCX: {len(docxs)}" if files else "data/ 目录为空，请放入文档"))

# 输出
print("=" * 56)
print("  MMD Transaction — 环境检查")
print("=" * 56)
for label, status, detail in CHECKS:
    icon = {"OK": "[OK]", "WARN": "[WARN]", "MISSING": "[MISS]", "FAIL": "[FAIL]", "EMPTY": "[EMPTY]"}[status]
    line = f"  {icon} {label}"
    if detail:
        line += f"  — {detail}"
    print(line)

fail = sum(1 for _, s, _ in CHECKS if s in ("MISSING", "FAIL"))
print("=" * 56)
if fail:
    print(f"  共 {fail} 项缺失，请先修复后再运行 rag_app.py")
else:
    print("  所有检查通过，可以运行: python rag_app.py")

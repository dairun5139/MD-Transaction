# MMD Transaction — 蒙东新能源电站交易 RAG 知识库

本地化 RAG 智能问答系统。以蒙东电力交易规则汇编、交易员培训教材等文档为知识源，结合 Ollama 本地模型（DeepSeek-R1 + nomic-embed-text），实现电力交易政策的精准检索与证据溯源问答。**数据全程不出本机。**

---

## 一、技术架构

```
用户提问
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│                    RAG 问答链 (每次提问触发)                    │
│                                                              │
│  FAISS 向量检索                Prompt 组装             Ollama │
│  nomic-embed-text (768维)  →   Context + Question  →  deepseek-r1:1.5b │
│  文档均衡 + 权重调整            证据约束模板            推理生成 │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
答案 + 参考片段 [S1][S2]... + 日志写入 logs/rag_trace.jsonl


离线索引管线 (首次运行 / 重建索引时触发)

  data/*.pdf ──┐
  data/*.docx ─┤
               ▼
  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌─────────────────────┐
  │ 文档加载       │   │ 文本清洗      │   │ 数据脱敏      │   │ 文本分块              │
  │ PyPDFLoader  │ → │ clean_text() │ → │ masker.py    │ → │ RecursiveCharSplitter │
  │ Docx2txtLoader│  │ 去控制字符/规范│   │ 12条正则规则  │   │ chunk=650, overlap=100 │
  └──────────────┘   └──────────────┘   └──────────────┘   └──────────┬──────────┘
                                                   │
                                                   ▼
  ┌──────────────────────────────────────────────────────────┐
  │              FAISS 向量库 (默认) 或 ChromaDB (可选)         │
  │     OllamaEmbeddings → nomic-embed-text → 768维持久化      │
  └──────────────────────────────────────────────────────────┘
```

### 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| LLM | Ollama + deepseek-r1:1.5b | 本地推理，HTTP API (`localhost:11434`) |
| 嵌入模型 | Ollama + nomic-embed-text | 768维，HTTP API，无 PyTorch 依赖 |
| AI 框架 | LangChain | 文档加载 → 分块 → 向量库 → 检索编排 |
| 向量库 (默认) | FAISS | 纯 NumPy，Windows 无崩溃风险 |
| 向量库 (可选) | ChromaDB | 设置 `RAG_VECTOR_BACKEND=chroma` |
| 文档解析 | pypdf + docx2txt | PDF/Word 文本提取 |
| 脱敏 | masker.py | 12条正则规则，可独立开关 |

---

## 二、环境要求

### 2.1 基础环境

| 组件 | 要求 | 检查命令 |
|------|------|----------|
| 操作系统 | Windows 10/11 x64 | — |
| Python | ≥ 3.10 | `python --version` |
| Python 环境 | PyCharm 项目虚拟环境 | PyCharm 右下角解释器 / `python -c "import sys; print(sys.executable)"` |
| Ollama | 最新版 | `ollama --version` |

### 2.2 模型拉取（仅首次）

```powershell
ollama pull deepseek-r1:1.5b
ollama pull nomic-embed-text
ollama list          # 确认两个模型都已就绪
```

### 2.3 Python 依赖

核心依赖（`requirements.txt`）：

```
requests
langchain
langchain-community
langchain-text-splitters
langchain-chroma
chromadb
faiss-cpu
pypdf
docx2txt
python-dotenv
```

可选依赖（未来混合检索 / 评测，当前主链路未使用）：

```
jieba
rank-bm25
```

安装：

```powershell
python -m pip install -r requirements.txt
```

> 项目已在 PyCharm 虚拟环境中运行。请优先使用 PyCharm Terminal 或 PyCharm Run Configuration 对应的解释器执行命令；如使用 Conda 环境，可按需替换为 `conda run -n <环境名> python ...`。

---

## 三、快速启动

### 3.1 确认知识文档

`data/` 目录下应有：

| 文件 | 内容 |
|------|------|
| `20251021010756789.pdf` | 蒙东电力交易规则/通知（~700页） |
| `蒙东新能源电站交易规则汇编_AI算法开发版.docx` | 规则汇编 |
| `蒙东电力交易市场交易员培训教材.pdf` | 交易员培训教材 |

### 3.2 启动 Ollama

```powershell
ollama serve
```

### 3.3 启动 Web 问答服务

```powershell
cd "D:\Project Repository\md_transaction"
python check_env.py
uvicorn api_app:app --host 127.0.0.1 --port 8000
```

浏览器访问：

```text
http://127.0.0.1:8000/
```

Apifox 可调试接口：

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/health` | 服务、索引、Ollama 状态 |
| `GET` | `/api/index/status` | 索引文件、manifest、召回参数 |
| `POST` | `/api/ask` | 客户问答接口 |

`POST /api/ask` 请求示例：

```json
{
  "question": "蒙东电力交易的中长期合约如何结算？"
}
```

### 3.4 命令行运行

```powershell
cd "D:\Project Repository\md_transaction"
python check_env.py    # 环境检查
python rag_app.py      # 启动问答
```

首次运行自动完成：文档加载 → 文本清洗 → 脱敏 → 分块 → 向量化 → 构建 FAISS 索引。后续启动直接加载已有索引，秒级就绪。

### 3.5 问答交互

```
>>> 蒙东电力交易的中长期合约如何结算？
```

输出包含：模型回答 + 参考片段 `[S1][S2]...` + 文件/页码/score/chunk_id/摘录。日志写入 `logs/rag_trace.jsonl`。

输入 `quit` / `exit` / `q` 退出。

---

## 四、配置参数

所有参数通过环境变量或直接编辑 `rag_app.py` 修改。

### 4.1 核心参数

| 参数 | 环境变量 | 默认值 | 作用 |
|------|----------|--------|------|
| `LLM_MODEL` | `RAG_LLM_MODEL` | `deepseek-r1:1.5b` | 生成模型 |
| `EMBED_MODEL` | `RAG_EMBED_MODEL` | `nomic-embed-text` | 嵌入模型 |
| `CHUNK_SIZE` | `RAG_CHUNK_SIZE` | 650 | 文本块大小（字符数） |
| `CHUNK_OVERLAP` | `RAG_CHUNK_OVERLAP` | 100 | 相邻块重叠字符数 |
| `RETRIEVAL_K` | `RAG_RETRIEVAL_K` | 10 | 最终送入 LLM 的片段数 |
| `OLLAMA_BASE_URL` | `RAG_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 服务地址 |

### 4.2 文档均衡检索

避免 377 页大 PDF 垄断召回结果：

| 参数 | 环境变量 | 默认值 | 作用 |
|------|----------|--------|------|
| `CANDIDATE_K` | `RAG_CANDIDATE_K` | 120 | 候选召回数（先宽召回，再均衡筛选） |
| `MAX_CHUNKS_PER_SOURCE` | `RAG_MAX_CHUNKS_PER_SOURCE` | 5 | 每个文档最多保留的片段数 |

文档权重（FAISS 距离越小越相似，高权重 = 除以权重使排名更靠前）：

```python
DOC_WEIGHTS = {
    "蒙东新能源电站交易规则汇编_AI算法开发版.docx": 1.40,
    "蒙东电力交易市场交易员培训教材.pdf": 1.25,
    "20251021010756789.pdf": 1.00,
}
```

检索流程：FAISS 召回 120 条候选 → 按权重调整分数 → 每文档最多取 5 条 → 最终输出 10 条。

**当前索引快照**（`faiss_index/`）：

| 文件 | Chunks | 占比 | 页面跨度 |
|------|--------|------|------|
| `20251021010756789.pdf` | 451 | 88.1% | 377 页 |
| `蒙东电力交易市场交易员培训教材.pdf` | 46 | 9.0% | 24 页 |
| `蒙东新能源电站交易规则汇编_AI算法开发版.docx` | 15 | 2.9% | 1 段落 |

> 总计 512 chunks，768维向量，chunk 平均约 456 字符。重建索引已应用文本清洗，控制字符/替换字符噪声为 0。大 PDF 占比约 88%，仍需文档均衡避免垄断召回。每条 chunk 包含 `chunk_id`、`doc_id`、`filename`、`page_label`、`section_title`、`chunk_index`、`text_hash` 等 metadata 字段。

**查看索引状态**：

```powershell
python -c "
import pickle, faiss; from collections import Counter; from pathlib import Path
with open('faiss_index/index.pkl','rb') as f: ds, _ = pickle.load(f)
c = Counter(ds._dict[id].metadata.get('filename','?') for id in ds._dict.keys())
for k,v in c.most_common(): print(f'  {k}: {v}')
idx = faiss.read_index('faiss_index/index.faiss')
print(f'  dim={idx.d}, total={idx.ntotal}')
"
```

### 4.3 向量库后端切换

```powershell
# 默认 FAISS
python rag_app.py

# 切换到 ChromaDB
$env:RAG_VECTOR_BACKEND="chroma"
python rag_app.py
```

### 4.4 数据脱敏配置

编辑 `masker.py` 中 `MASK_CONFIG` 字典，每项可独立开关：

| 规则 | 默认 | 脱敏内容 |
|------|------|----------|
| `phone` | True | 手机号、座机号 |
| `id_card` | True | 身份证号 |
| `credit_code` | True | 统一社会信用代码 |
| `email` | True | 邮箱地址 |
| `bank_account` | True | 银行账号 |
| `amount` | False | 金额数值 |
| `company_name` | False | 公司名称 |
| `address` | False | 详细地址 |
| `price` | False | 电价数值 |
| `quantity` | False | 电量数值 |
| `ip` | False | IP 地址 |
| `person_name` | False | 人名（误报率高） |

预览脱敏效果（不入库）：

```powershell
python masker.py --preview data/
```

> 修改脱敏配置后需删除索引目录重建。

---

## 五、日常维护

### 5.1 新增文档

```powershell
# 将新文档放入 data/ → 删除索引 → 重建
rmdir /s /q faiss_index
python rag_app.py
```

### 5.2 仅调整检索/回答逻辑

修改 `RAG_RETRIEVAL_K`、`RAG_CANDIDATE_K`、`RAG_MAX_CHUNKS_PER_SOURCE`、`DOC_WEIGHTS`、`RAG_PROMPT` 或 `_retrieve()` 后，**无需重建索引**，重启即可生效。

### 5.3 更换模型

编辑 `rag_app.py` 顶部常量，或设置环境变量：

```powershell
$env:RAG_LLM_MODEL="qwen2.5:7b"
python rag_app.py
```

### 5.4 重置到初始状态

```powershell
rmdir /s /q faiss_index
rmdir /s /q chroma_db
rmdir /s /q logs
python rag_app.py
```

---

## 六、项目文件结构

```
md_transaction/
├── README.md                       ← 本文档
├── rag_app.py                      ← RAG 核心入口（加载→清洗→脱敏→分块→检索→问答）
├── api_app.py                      ← FastAPI 接口和客户问答页面
├── masker.py                       ← 数据脱敏模块
├── check_env.py                    ← 环境检查
├── requirements.txt                ← Python 依赖
├── data/                           ← 知识源文档
├── faiss_index/                    ← FAISS 向量索引（自动生成；重建索引时写入 manifest.json）
├── chroma_db/                      ← ChromaDB 向量库（可选，自动生成）
└── logs/                           ← 问答日志 rag_trace.jsonl
```

---

## 七、常见问题

### Q1: 终端使用的不是 PyCharm 虚拟环境

优先从 PyCharm Terminal 或 Run Configuration 启动；也可以用 `python -c "import sys; print(sys.executable)"` 确认当前解释器是否为项目虚拟环境。

### Q2: FAISS 写入报 `Illegal byte sequence`

项目路径包含中文时 FAISS 可能写索引失败。将项目放在纯英文路径下即可。

### Q3: `OllamaEmbeddings object is not callable`

`rag_app.py` 中 `OllamaEmbeddings` 类已包含 `__call__` 方法。如遇此报错，检查是否使用了旧版代码。

### Q4: 连接 Ollama 失败

```powershell
ollama serve          # 确认服务运行
ollama list           # 确认模型已拉取
```

### Q5: ChromaDB 崩溃（access violation）

Windows + ChromaDB 1.x 存在已知崩溃问题，项目默认使用 FAISS。如需 ChromaDB，设置 `$env:RAG_VECTOR_BACKEND="chroma"`。

### Q6: 回答与问题不相关

- 尝试调整 `CHUNK_SIZE` / `CHUNK_OVERLAP` 后重建索引
- 检查 `DOC_WEIGHTS` 权重是否合理
- 查看 `logs/rag_trace.jsonl` 排查召回质量

---

## 八、关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| LLM 调用方式 | `requests` 直连 Ollama HTTP API | 绕开 langchain-ollama C++ 绑定，消除 Windows segfault |
| 嵌入模型 | nomic-embed-text (Ollama HTTP) | 绕开 PyTorch/sentence-transformers C 扩展 |
| 默认向量库 | FAISS | ChromaDB 1.x Windows 下存在 HNSW 崩溃风险 |
| 检索策略 | 候选召回 → 权重调整 → 文档均衡 | 避免大 PDF 因 chunk 数量多而垄断召回 |
| 脱敏位置 | 文档加载后、分块前 | 防止敏感字段被块边界截断 |
| Prompt 设计 | 证据约束 + 来源引用 + 结构化输出 | 降低幻觉，支持回答溯源 |
| 日志 | JSONL 格式写入 logs/ | 支持每次问答的质量回溯和召回调试 |

---

## 九、扩展方向

1. **混合检索**：FAISS 向量 + BM25 关键词 + RRF 融合 + Reranker 重排
2. **结构化切片**：按章/节/条/表格切分，保留章节标题与条款号
3. **评测闭环**：建立固定测试集（`eval/questions.jsonl`），每次调参后回归
4. **更强模型**：如硬件允许，评估 `deepseek-r1:7b` 或 `qwen2.5:7b`
5. **Web UI**：Streamlit 或 Gradio 可视化界面

---

## 十、快捷脚本

创建 `run.bat`，双击启动：

```batch
@echo off
chcp 65001 >nul
cd /d "D:\Project Repository\md_transaction"
python rag_app.py
pause
```

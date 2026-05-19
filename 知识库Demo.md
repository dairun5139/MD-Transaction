# 知识库 Demo — 蒙东新能源电站交易 RAG 知识库 技术详解

> 面向教学的完整技术文档。涵盖项目架构、技术栈协同机制、环境配置、逐文件说明、数据管线及扩展建议。

---

## 一、项目一句话概括

一个**本地运行、数据不出本机**的电力交易政策智能问答系统。上传 PDF/Word 文档 → 自动构建知识库 → 用自然语言提问 → DeepSeek-R1 基于原文生成回答。

---

## 二、当前运行环境

### 2.1 基础环境

| 项目 | 版本/信息 |
|------|-----------|
| **操作系统** | Windows 10 Home China 10.0.19045 |
| **Python** | 3.10.20 (Anaconda) |
| **Shell** | PowerShell 7 / bash (Git for Windows) |

### 2.2 Ollama 服务 (本地 LLM + 嵌入)

| 模型 | 大小 | 用途 |
|------|------|------|
| `deepseek-r1:1.5b` | 1.1 GB | 基于检索到的上下文生成回答（推理模型，含思维链） |
| `nomic-embed-text:latest` | 274 MB | 将中文文本编码为 768 维向量，用于向量相似度检索 |

API 端口：`http://localhost:11434`

### 2.3 核心 Python 依赖

| 包 | 版本 | 角色 |
|------|------|------|
| `langchain` | 1.3.1 | RAG 流程编排（文档→分块→向量库→检索→回答） |
| `langchain-community` | 0.4.1 | 文档加载器：`PyPDFLoader`、`Docx2txtLoader` |
| `langchain-chroma` | 1.1.0 | ChromaDB 向量库封装 |
| `langchain-text-splitters` | 1.1.2 | `RecursiveCharacterTextSplitter` 文本分块 |
| `chromadb` | 1.5.9 | 嵌入式向量数据库（⚠ 已知 Windows segfault 问题） |
| `pypdf` | 6.11.0 | PDF 文档解析 |
| `docx2txt` | 0.9 | Word 文档解析 |
| `requests` | 2.34.2 | 直接调用 Ollama HTTP API（绕过所有 C 扩展库） |
| `sentence-transformers` | 5.5.0 | 仅保留用于兼容性（实际嵌入已迁移到 Ollama） |

> **不再依赖 PyTorch**：嵌入模型从 `BAAI/bge-small-zh-v1.5`（HuggingFaceEmbeddings + PyTorch）全面迁移至 `nomic-embed-text`（Ollama HTTP API），消除了 Windows 上 PyTorch C++ 扩展的 segfault 问题。

---

## 三、系统架构全景图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        终端交互层 (CLI)                               │
│                   interactive_qa() — 无限循环问答                      │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ question
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      RAG 问答链 (每次提问触发)                         │
│                                                                      │
│  ┌──────────────────┐   ┌──────────────────┐   ┌─────────────────┐  │
│  │ ChromaDB 检索     │   │ Prompt 模板       │   │ Ollama HTTP API │  │
│  │ nomic-embed-text  │──▶│ Context + Question│──▶│ deepseek-r1     │  │
│  │ 编码 (768维)      │   │ 组装为完整 Prompt  │   │ 推理生成回答     │  │
│  │ 返回 top-4 文本块  │   │                  │   │                 │  │
│  └──────────────────┘   └──────────────────┘   └─────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

```
┌─────────────────────────────────────────────────────────────────────┐
│                     离线索引管线 (首次运行/重建时触发)                    │
│                                                                      │
│  data/*.pdf ──┐                            ┌── 手机号/身份证/邮箱      │
│  data/*.docx ─┤                            │   公司名/地址/电价/电量   │
│               ▼                            │                         │
│  ┌─────────────────┐   ┌──────────────┐   ┌┴────────────────────┐   │
│  │ 文档加载          │   │ 数据脱敏      │   │ 文本分块              │   │
│  │ PyPDFLoader     │──▶│ masker.py    │──▶│ RecursiveCharSplitter│   │
│  │ Docx2txtLoader  │   │ 12条正则规则  │   │ chunk=500, over=50   │   │
│  └─────────────────┘   └──────────────┘   └──────────┬─────────┘   │
│                                                      │              │
│                                                      ▼              │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    ChromaDB 向量化存储                         │   │
│  │  nomic-embed-text → 768维向量 → chroma_db/ 持久化             │   │
│  │  后续启动自动检测 chroma.sqlite3，跳过索引直接进入问答          │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 四、技术栈分层详解

### 4.1 LLM 推理层 — Ollama + DeepSeek-R1

| 组件 | 说明 |
|------|------|
| **Ollama** | 本地 LLM 运行时，提供 HTTP API (`localhost:11434`)，管理模型的加载、推理、卸载 |
| **deepseek-r1:1.5b** | DeepSeek-R1 的 1.5B 蒸馏版本，支持 32K 上下文，推理链式思维（Chain-of-Thought），返回 JSON 含 `response` + `thinking` 两个字段 |

**为何选择 Ollama？**
- 数据完全不出本机，满足电力交易数据安全合规要求
- 无需 GPU，CPU 可运行（1.5B 模型推理延迟约 1-3 秒）
- 标准 HTTP API（`POST /api/generate`、`POST /api/embeddings`），任何语言都能调用

**调用方式（rag_app.py 第 128-134 行）**：
```python
resp = requests.post(
    "http://localhost:11434/api/generate",
    json={"model": "deepseek-r1:1.5b", "prompt": prompt_text, "stream": False},
    timeout=120,
)
return resp.json().get("response", "")
```

> **设计决策**：原设计使用 `langchain-ollama` 和 `langchain-huggingface`，但在 Windows 上这些库内部的 C++ 绑定 / PyTorch 运行时触发 Segmentation Fault（进程直接崩溃，无 Python 异常栈）。彻底改为纯 HTTP 调用后消除了此类问题。

---

### 4.2 AI 编排层 — LangChain

| 包 | 在项目中的角色 |
|------|------|
| `langchain` | 顶层胶水，串联 Document → Splitter → VectorStore 整个链 |
| `langchain-community` | 文档加载器：`PyPDFLoader`、`Docx2txtLoader` |
| `langchain-text-splitters` | `RecursiveCharacterTextSplitter`：按段落→句子→逗号递进切分 |
| `langchain-chroma` | `Chroma` 向量库封装：`from_documents()` 写入、`similarity_search()` 检索 |

> `langchain-huggingface` 和 `langchain-ollama` 已不再使用，对应功能由自定义 `OllamaEmbeddings` 类 + `requests` 直接 HTTP 调用替代。

---

### 4.3 嵌入模型层 — OllamaEmbeddings (自定义)

| 特性 | 说明 |
|------|------|
| **模型** | `nomic-embed-text`（Ollama 内置，无需单独下载） |
| **调用方式** | HTTP POST `http://localhost:11434/api/embeddings` |
| **输出维度** | 768 维浮点向量 |
| **实现位置** | `rag_app.py` 第 30-57 行 `OllamaEmbeddings` 类 |
| **方法** | `embed_documents(texts)` 批量编码 / `embed_query(text)` 单条查询 |

**为何不继续用 BGE？**

| 对比维度 | 原方案 (BGE) | 现方案 (nomic-embed-text) |
|------|-------------|------------------------|
| 运行时 | PyTorch + sentence-transformers | Ollama HTTP API |
| 模型加载 | ~100MB 权重每次启动加载 | Ollama 管理，常驻内存 |
| Windows 稳定性 | 偶发 segfault（C++ 扩展） | 纯 HTTP，无 C 扩展问题 |
| 向量维度 | 512 | 768 |
| 中文性能 | 优秀（专为中文优化） | 可用（通用多语言模型） |

---

### 4.4 向量存储层 — ChromaDB

| 特性 | 说明 |
|------|------|
| **类型** | 嵌入式向量数据库（无独立服务进程） |
| **版本** | 1.5.9 |
| **存储格式** | `chroma.sqlite3`（元数据索引）+ UUID 目录下数据文件 |
| **持久化** | 本地目录 `chroma_db/`，重启不丢失 |
| **检索方式** | 余弦相似度（cosine similarity），默认返回 top-K 最相近文本 |

> **⚠ 已知问题**：ChromaDB 1.x 在 Windows 上存在已知的 HNSW 索引库 segfault（退出码 0xC0000005），是社区广泛报告的普遍问题（chroma-core/chroma#3058、#2534、#2856）。症状为进程直接崩溃无异常栈。如遇此问题，可考虑替换为 FAISS 向量库。

---

### 4.5 文档解析层 — PyPDF + docx2txt

| 库 | 处理对象 | 原理 |
|------|------|------|
| `pypdf` | PDF 文档 | 逐页提取文本流，保留换行结构 |
| `docx2txt` | Word 文档 | 解析 OOXML 格式，提取正文 + 表格文本 |

> 两个库都是纯 Python 实现，无需系统级依赖（如 LibreOffice、Poppler）。

---

### 4.6 文本分块策略 — RecursiveCharacterTextSplitter

```python
separators = ["\n\n", "\n", "。", "；", "，", " ", ""]
chunk_size = 500      # 每块 500 字符
chunk_overlap = 50    # 相邻块重叠 50 字符
```

**递进分割逻辑**：先按段落分（`\n\n`），超过 500 字的再按句子分（`。`），还不够就按逗号（`，`）。重叠 50 字符保证"上网电价 0.35 元/kWh"这类关键信息不会因块边界被截断。

---

### 4.7 数据安全层 — masker.py

在文档加载后、分块入库前，对文本进行 12 条正则规则的自动化脱敏：

| 层级 | 规则 | 示例效果 |
|------|------|------|
| 结构化数据 | 手机号 | `13812345678` → `138****5678` |
| 结构化数据 | 身份证号 | `152201199001011234` → `152201********1234` |
| 结构化数据 | 统一社会信用代码 | `91150100MA0NXXXXX` → `9115**********XXXX` |
| 结构化数据 | 邮箱 | `zhang@energy.com` → `z**g@energy.com` |
| 结构化数据 | 银行账号 | `6222021234567890123` → `****0123` |
| 结构化数据 | 金额 | `3500万元` → `***万元` |
| 名称实体 | 公司名称 | `奈曼旗远景风电场有限公司` → `奈***司` |
| 名称实体 | 详细地址 | `内蒙古自治区通辽市科尔沁区XX路XX号` → `内蒙古自治区***` |
| 数值模糊 | 电价 | `0.35元/kWh` → `[0-1]元/kWh` |
| 数值模糊 | 电量 | `12500万kWh` → `约1万kWh` |

**开关机制**：`MASK_CONFIG` 字典，每项可独立设为 `True`/`False`。白名单包含 `国家发展改革委`、`国家能源局`、`蒙东电力交易中心` 等权威机构名称，不会被脱敏。

---

## 五、逐文件详解

### 5.1 `rag_app.py` — RAG 核心入口（208 行）

**结构分解**：

```
行 1-6    ：模块 docstring + 导入 (pathlib, requests, masker)
行 10-21  ：配置常量（路径、模型名、chunk 参数、Prompt 模板）
行 31-57  ：OllamaEmbeddings 类（HTTP API 向量化，替代 PyTorch）
行 63-76  ：load_documents() — PDF/Word 加载
行 80-91  ：split_documents() — 文本分块
行 94-105 ：build_vectorstore() — 向量库构建（首次运行）
行 108-119：load_vectorstore() — 向量库加载（缓存命中）
行 122-138：ask() — 核心问答（检索 + 调用 LLM）
行 142-174：interactive_qa() — 交互循环
行 177-207：main() — 入口（检测缓存 / 重建索引）
```

**关键配置项**：

| 常量 | 值 | 影响 |
|------|------|------|
| `LLM_MODEL` | `deepseek-r1:1.5b` | 回答的推理深度和准确性 |
| `EMBED_MODEL` | `nomic-embed-text` | 文本向量化质量 |
| `CHUNK_SIZE` | 500 | 检索粒度 |
| `CHUNK_OVERLAP` | 50 | 防止语义断裂 |
| `RETRIEVAL_K` | 4 | 每次给 LLM 提供多少参考段落 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 服务地址 |

---

### 5.2 `masker.py` — 数据脱敏模块（399 行）

独立脱敏引擎，可脱离 `rag_app.py` 独立运行。

**三层设计**：
```
第一层：结构化数据（高置信度正则）
  phone → id_card → credit_code → email → bank_account → ip → amount
第二层：名称类实体
  company_name → address → person_name
第三层：数值模糊化
  price → quantity
```

**预览模式**：
```bash
python masker.py --preview data/              # 预览全部文档
python masker.py --preview data/某文件.docx    # 预览单个文件
```

---

### 5.3 `check_env.py` — 环境检查脚本（67 行）

验证 9 个 Python 包、Python 版本、Ollama 服务状态、知识源文件是否存在。

---

### 5.4 `data/` — 知识源目录

| 文件 | 大小 | 内容 |
|------|------|------|
| `20251021010756789.pdf` | 3.0 MB | 蒙东电力交易规则/通知文档 |
| `蒙东新能源电站交易规则汇编_AI算法开发版.docx` | 47 KB | 规则汇编（Word 格式） |
| `蒙东电力交易市场交易员培训教材.pdf` | 5.1 MB | 交易员培训教材 |

> `data/` 未被 `.gitignore` 排除——知识文档是项目核心资产，应纳入版本控制。

---

### 5.5 `chroma_db/` — 向量库持久化目录

自动生成，不可手动修改。删除即重建：

```bash
rm -rf chroma_db && python rag_app.py
```

---

### 5.6 `all-in-rag/` — RAG 学习参考代码

来自 GitHub 的《All-in-RAG》配套仓库（C1-C9 章节），仅供学习参考，不参与主项目运行。

---

## 六、数据管线完整流程

### 6.1 首次启动（冷启动）

```
步骤 1：文档加载     load_documents()          PDF + Word 逐页读取
步骤 2：数据脱敏     mask_documents()          敏感字段全部替换
步骤 3：文本分块     split_documents()         chunk=500, overlap=50
步骤 4：向量化       OllamaEmbeddings()        调用 nomic-embed-text HTTP API
步骤 5：向量库构建   ChromaDB.from_documents()  写入 chroma_db/
步骤 6：进入问答循环  interactive_qa()         等待用户输入
```

### 6.2 后续启动（热启动）

```
步骤 1：检测 chroma.sqlite3 存在  → 直接加载向量库，跳过 1-5
步骤 2：进入问答循环
```

### 6.3 单次问答流程

```
用户提问 "蒙东新能源电力交易的中长期合约是如何结算的？"
  │
  ▼
ChromaDB.similarity_search(question, k=4)
  │  OllamaEmbeddings.embed_query() → HTTP POST /api/embeddings → nomic-embed-text
  │  返回 768 维向量，计算余弦距离
  ▼
返回 top-4 最相似文本块
  │
  ▼
组装 Prompt（RAG_PROMPT 模板填充 context + question）
  │
  ▼
HTTP POST /api/generate → deepseek-r1:1.5b 推理
  │  请求 body: {"model": "deepseek-r1:1.5b", "prompt": "...", "stream": false}
  │  响应含 "response" + "thinking" 两个字段
  ▼
返回回答（取 response 字段）
```

---

## 七、关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| LLM 调用方式 | HTTP API 直接调用 | 绕过 langchain-ollama 的 C++ 绑定，消除 segfault |
| 嵌入模型 | nomic-embed-text (Ollama) | 绕开 PyTorch/sentence-transformers 的 C 扩展，消除 segfault |
| 向量数据库 | ChromaDB（嵌入式） | 零配置，SQLite 单文件，无需独立服务 |
| 脱敏位置 | 加载→脱敏→分块 | 防止敏感字段被块边界截断 |
| Prompt 模板 | 简洁两段式 | DeepSeek-R1 不需复杂指令，上下文+问题即可 |

---

## 八、Windows 已知问题与解决方案

### 8.1 ChromaDB Segfault（当前存在）

**症状**：`similarity_search()` / `get_collection()` 时进程崩溃，退出码 `0xC0000005`，无 Python 异常。

**原因**：ChromaDB 1.x 底层 HNSW 索引库在 Windows 上存在内存访问 bug，是社区广泛报告的问题（chroma-core/chroma#3058, #2534, #2856, #6052）。

**备选方案**：
- 替换为 **FAISS** 向量库（`langchain-community.vectorstores.FAISS`），纯 NumPy 实现
- 使用 **Docker 运行 ChromaDB** 并改用 `HttpClient` 连接
- 降级到 `chromadb==0.5.23`

### 8.2 PyTorch Segfault（已解决）

已将 `HuggingFaceEmbeddings` (BAAI/bge-small-zh-v1.5) 替换为 `OllamaEmbeddings` (nomic-embed-text)，不再依赖 PyTorch。

### 8.3 langchain-ollama Segfault（已解决）

已将 `langchain-ollama` 的 ChatOllama 替换为直接 `requests.post()` HTTP 调用。

---

## 九、快速命令速查

```bash
# 启动 Ollama 服务
ollama serve

# 拉取模型（首次使用）
ollama pull deepseek-r1:1.5b
ollama pull nomic-embed-text

# 环境检查
python check_env.py

# 启动问答（首次自动建库）
python rag_app.py

# 预览脱敏效果
python masker.py --preview data/

# 删除向量库并重建
rm -rf chroma_db && python rag_app.py

# 查看已安装模型
ollama list

# 测试 LLM 独立运行
ollama run deepseek-r1:1.5b "你好"

# 测试嵌入 API
curl http://localhost:11434/api/embeddings -d '{"model":"nomic-embed-text","prompt":"test"}'
```

---

## 十、技术栈关系速记

```
用户问题
  ↓
rag_app.py (LangChain 编排)
  ├── ChromaDB ← OllamaEmbeddings ← nomic-embed-text (HTTP)
  │     ↑                                        ↑
  │   检索相似文本块                  Ollama /api/embeddings
  │
  ├── Prompt 组装 ← RAG_PROMPT 模板
  │
  └── Ollama HTTP API ← deepseek-r1:1.5b
        ↑
    Ollama /api/generate (本地推理服务)

数据入库 (仅首次/重建)
  ├── data/*.pdf → PyPDFLoader
  ├── data/*.docx → Docx2txtLoader
  ├── masker.py → 12条正则脱敏
  └── RecursiveCharacterTextSplitter → ChromaDB

已移除的依赖（因 Windows segfault）：
  ✗ langchain-huggingface  ✗ langchain-ollama  ✗ PyTorch
```

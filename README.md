# MMD Transaction — 蒙东新能源电站交易 RAG 知识库 操作说明书

## 一、项目简介

本项目构建了一套基于 **RAG（检索增强生成）** 架构的本地化智能知识库，以蒙东电力交易规则汇编、交易员培训教材等文档为知识源，结合本地 Ollama DeepSeek-R1 大模型，实现电力交易政策规则的精准检索与智能问答。

**核心能力**：上传 PDF/Word 文档 → 自动解析入库 → 自然语言提问 → 基于原文的带上下文回答。

---

## 二、环境要求

### 2.1 系统环境

| 组件 | 版本要求 | 检查方式 |
|------|----------|----------|
| Windows 系统 | Windows 10/11 x64 | — |
| Python | ≥ 3.10 | `python --version` |
| Conda | 任意版本 | `conda --version` |
| Ollama | 最新版 | `ollama --version` |

### 2.2 Python 依赖框架

#### RAG 核心框架

| 包 | 版本 | 用途 |
|---|---|---|
| `langchain` | ≥ 0.3.0 | RAG 流程编排（文档加载→分块→检索→生成） |
| `langchain-community` | ≥ 0.3.0 | 社区扩展（ChromaDB、Unstructured 集成等） |
| `langchain-ollama` | ≥ 0.2.0 | Ollama LLM 接入 |
| `langchain-text-splitters` | ≥ 0.3.0 | 文本分块策略（递归字符切分） |

#### 向量数据库

| 包 | 版本 | 用途 |
|---|---|---|
| `chromadb` | ≥ 0.5.0 | 本地向量存储与相似度检索（默认方案） |
| `faiss-cpu` | ≥ 1.7.0 | Facebook 向量索引（备选，C8 章节使用） |
| `pymilvus` | 2.5.11 | Milvus 向量数据库（备选，C9 章节使用） |

#### 嵌入模型

| 包 | 版本 | 用途 |
|---|---|---|
| `sentence-transformers` | ≥ 3.0.0 | 本地运行 BGE 中文嵌入模型（`bge-small-zh-v1.5`） |

#### 文档加载与解析

| 包 | 版本 | 用途 |
|---|---|---|
| `pypdf` | ≥ 5.0.0 | PDF 文档文本提取 |
| `docx2txt` | ≥ 0.8 | Word 文档文本提取 |
| `unstructured` | 0.18.11 | 通用文档解析（PDF/Word/Markdown/图片OCR） |
| `Markdown` | 3.8.2 | Markdown 解析 |

#### LLM / API 接入

| 包 | 版本 | 用途 |
|---|---|---|
| `openai` | ≥ 1.86.0 | OpenAI 兼容 API 调用 |
| `langchain-deepseek` | 0.1.4 | DeepSeek API 接入（C9 Agent 章节） |

#### 深度学习框架（all-in-rag 学习代码）

| 包 | 版本 | 用途 |
|---|---|---|
| `torch` | 2.6.0 | PyTorch 深度学习框架 |
| `transformers` | ≥ 4.40.0 | HuggingFace 模型加载与推理 |
| `accelerate` | ≥ 0.20.0 | 分布式/混合精度推理加速 |
| `datasets` | ≥ 2.14.0 | 数据集加载与预处理 |

#### LlamaIndex 生态（all-in-rag 学习代码）

| 包 | 用途 |
|---|---|
| `llama-index` / `llama-index-core` | 备选 RAG 框架 |
| `llama-index-embeddings-huggingface` | HuggingFace 嵌入模型集成 |
| `llama-index-llms-openai` / `llama-index-llms-deepseek` | LLM 集成 |

#### 图数据库

| 包 | 版本 | 用途 |
|---|---|---|
| `neo4j` | ≥ 5.0.0 | 知识图谱存储与查询（C9 章节） |

#### 通用工具

| 包 | 用途 |
|---|---|
| `numpy` / `pandas` / `scipy` | 数值计算与数据处理 |
| `scikit-learn` | 机器学习工具（特征提取、相似度） |
| `python-dotenv` | 环境变量管理 |
| `tqdm` | 进度条显示 |
| `pydantic` | 数据校验 |
| `jieba` | 中文分词 |
| `rank-bm25` | BM25 关键词检索 |
| `tiktoken` | Token 计数 |
| `openpyxl` | Excel 读写 |
| `requests` | HTTP 请求 |

> **说明**：项目根目录 `requirements.txt` 仅包含 RAG 核心运行所需的最小依赖（约 9 个包）。`all-in-rag/code/` 下各章节的 `requirements.txt` 包含学习参考代码的完整依赖，日常运行 `rag_app.py` 无需全部安装。

---

## 三、第一次启动（完整流程）

### 3.1 启动 Ollama 并拉取模型

```powershell
# 1. 启动 Ollama（双击桌面图标，或命令行启动）
ollama serve

# 2. 另开一个终端，拉取 DeepSeek-R1 模型（约 4.7GB，仅首次需要）
ollama pull deepseek-r1:latest

# 3. 验证模型已就绪
ollama list
```

> 输出中应能看到 `deepseek-r1:latest` 一项。

### 3.2 配置 Python 环境

```powershell
# 1. 打开 PowerShell，进入项目目录
cd "D:\研究_LIVE\组会\（项目3）蒙东新能源电站交易AI算法开发"

# 2. 安装项目依赖（约 1~2 分钟，仅首次需要）
conda run -n base pip install -r requirements.txt
```

> **为什么不直接用 `conda activate`？** 部分 Windows 机器上 `conda activate` 报错 `CommandNotFoundError`，即使运行 `conda init` 并重启终端也依然失败。用 `conda run -n base` 替代，效果完全相同，无需激活环境。详见 [第七章 Q1](#q1conda-activate--commandnotfounderror)。

> **国内加速**：如果下载慢，先设置 HuggingFace 镜像：
> ```powershell
> $env:HF_ENDPOINT = "https://hf-mirror.com"
> ```
> 然后再执行 `pip install -r requirements.txt`

### 3.3 确认知识文档已就位

确保 `data\` 目录下存在以下文件：

- `20251021010756789.pdf` — 交易规则/通知
- `蒙东新能源电站交易规则汇编_AI算法开发版.docx` — 规则汇编
- `蒙东电力交易市场交易员培训教材.pdf` — 培训教材

如需增加新文档，将 PDF 或 Word 文件放入 `data\` 目录，删除 `chroma_db\` 后重新启动即可重新索引。

### 3.4 环境检查

```powershell
conda run -n base python check_env.py
```

预期输出所有检查项都是 `[OK]`。如有 `[MISS]`，按提示安装缺失的包。

### 3.5 启动知识库问答

```powershell
conda run -n base python rag_app.py
```

**首次启动** 会自动完成：

```
[STEP 1/3] 加载文档...       ← 解析 PDF/Word，提取文本
[STEP 2/3] 文本分块...       ← 将长文本切分为 500 字左右的语义块
[STEP 3/3] 构建向量库...     ← 下载 BGE 中文嵌入模型 + 向量化写入 ChromaDB
```

随后进入交互问答界面：

```
==========================================================
  MMD Transaction RAG 知识库 — 交互问答
  模型: deepseek-r1:latest  |  检索条数: 4
  输入 'quit' 退出
==========================================================

>>> 请输入问题:
```

---

## 四、日常使用

### 4.1 启动问答

```powershell
cd "D:\研究_LIVE\组会\（项目3）蒙东新能源电站交易AI算法开发"
conda run -n base python rag_app.py
```

后续启动会自动跳过文档索引步骤，直接进入问答界面（秒级就绪）。

### 4.2 交互命令

| 输入 | 效果 |
|------|------|
| 任意问题 + 回车 | 检索相关文档段落，由 DeepSeek-R1 生成回答 |
| `quit` / `exit` / `q` | 退出程序 |
| `Ctrl + C` | 强制退出 |

### 4.3 回答逻辑

```
用户提问
  → BGE 嵌入模型将问题转为向量
  → ChromaDB 从知识库中检索最相关的 4 个文本块
  → 将 [上下文 + 问题] 组装为 Prompt
  → Ollama DeepSeek-R1 推理生成回答
  → 终端输出
```

---

## 五、维护操作

### 5.1 新增文档

```powershell
# 1. 将新文档放入 data\ 目录
# 2. 删除旧的向量库
rmdir /s chroma_db

# 3. 重新启动，自动重建索引
conda run -n base python rag_app.py
```

### 5.2 更新依赖包

```powershell
conda run -n base pip install --upgrade -r requirements.txt
```

### 5.3 更换模型

编辑 `rag_app.py` 第 23 行，将 `LLM_MODEL` 改为其他已拉取的模型名：

```python
LLM_MODEL = "qwen2.5:7b"   # 示例：改用通义千问
```

支持的模型可以从 `ollama list` 查看，或通过 `ollama pull <model>` 拉取新的。

### 5.4 调整检索参数

编辑 `rag_app.py` 中的配置常量：

| 参数 | 默认值 | 作用 |
|------|--------|------|
| `CHUNK_SIZE` | 500 | 文本块大小（字符数），越小检索越精准但丢失上下文 |
| `CHUNK_OVERLAP` | 50 | 相邻块重叠字符数，防止语义被截断 |
| `RETRIEVAL_K` | 4 | 每次检索返回的段落数，越大上下文越丰富但推理越慢 |

---

## 六、项目文件说明

```
（项目3）蒙东新能源电站交易AI算法开发/
├── README.md                       ← 本文档
├── MMD transaction.md              ← 项目架构文档
├── rag_app.py                      ← RAG 核心入口脚本
├── check_env.py                    ← 环境检查脚本
├── requirements.txt                ← Python 依赖清单
├── data/                           ← 知识源文档（用户维护）
├── chroma_db/                      ← 向量库数据（自动生成，勿手动修改）
└── all-in-rag/                     ← RAG 学习参考代码
```

---

## 七、常见问题

### Q1：`conda activate` → `CommandNotFoundError`

**报错全文**：
```
CommandNotFoundError: Your shell has not been properly configured to use 'conda activate'.
```

**原因**：部分 Windows 机器上 Conda 的 shell 初始化存在兼容问题，表现为：
- 运行 `conda init powershell`（或 `conda init cmd.exe`），输出显示 `no change`（配置文件已写入）
- 关闭并重启终端后，`conda activate` 依然报错 `CommandNotFoundError`

**解决方案（三选一）**：

| 方案 | 命令格式 | 推荐度 |
|------|----------|--------|
| `conda run` | `conda run -n base python rag_app.py` | **推荐** |
| 直接路径 | `"D:\Anaconda 3\python.exe" rag_app.py` | 可用 |
| `conda activate` | 需要 shell 正确初始化，部分机器顽固失效 | 不推荐 |

本项目所有命令已统一使用 `conda run -n base` 格式，无需 `conda activate`。

### Q2：启动时卡在"加载嵌入模型"

首次运行时需要从 HuggingFace 下载 `BAAI/bge-small-zh-v1.5` 模型（约 100MB）。
- 设置镜像：`$env:HF_ENDPOINT = "https://hf-mirror.com"`
- 或手动下载放到 `~/.cache/huggingface/hub/` 目录

### Q3：Ollama 连接失败

```
# 确认 Ollama 服务正在运行
ollama serve

# 确认模型已拉取
ollama list

# 测试模型是否正常
ollama run deepseek-r1:latest "你好"
```

### Q4：回答与问题不相关

- 可能知识库中确实没有相关信息 → DeepSeek-R1 会如实告知
- 可能是 chunk 切分不合理 → 删除 `chroma_db\`，调整 `CHUNK_SIZE` 后重建
- 可能是嵌入模型对中文理解不足 → 已在代码中选用中文优化的 `bge-small-zh-v1.5`

### Q5：想恢复到"首次启动"状态

```powershell
rmdir /s chroma_db
conda run -n base python rag_app.py
```

---

## 八、快捷启动脚本（可选）

在项目目录下创建 `run.bat`，双击即可启动：

```batch
@echo off
chcp 65001 >nul
cd /d "D:\研究_LIVE\组会\（项目3）蒙东新能源电站交易AI算法开发"
conda run -n base python rag_app.py
pause
```

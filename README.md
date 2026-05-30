# MD Transaction RAG 知识库

本项目是一个本地化电力交易规则问答系统。它将蒙东电力交易相关 PDF/DOCX 文档构建为本地向量知识库，通过 Ollama 本地模型完成检索增强问答，并在回答中返回来源片段、页码、score 和 chunk_id，便于追溯依据。

项目目标不是做一个通用聊天机器人，而是服务于电力交易规则查询、培训材料检索、政策依据定位和客户问答接口演示。数据、向量索引、问答日志均保留在本机。

## 一、项目任务

### 1. 知识库构建

- 从 `data/` 读取 PDF 和 DOCX 知识源。
- 清洗 PDF 抽取产生的控制字符、异常空白和替换字符。
- 对强隐私字段进行脱敏。
- 将长文档切分为适合检索和模型上下文的 chunk。
- 使用 `nomic-embed-text` 生成向量，并写入 FAISS 索引。
- 生成 `manifest.json`，记录索引构建参数和知识源文件状态。

### 2. 规则问答

- 接收用户关于蒙东电力交易规则、结算、申报、注册、市场主体、培训材料等问题。
- 从 FAISS 中召回候选片段。
- 对候选片段进行文档权重调整和来源均衡，避免大 PDF 垄断上下文。
- 使用证据约束 Prompt 调用本地 LLM 生成答案。
- 返回答案和来源片段，支持人工复核。

### 3. Web/API 服务

- 提供浏览器问答页面。
- 提供 Apifox 或其他客户端可调用的 REST API。
- 提供健康检查和索引状态查询。
- 支持后续接入企业微信、OA、前端系统或内部业务平台。

### 4. 运行追踪

- 每次问答写入 `logs/rag_trace.jsonl`。
- 日志记录问题、答案、来源片段、模型名和召回参数。
- 支持后续分析召回质量、定位错误答案、沉淀评测集。

## 二、技术架构

### 1. 总体链路

```text
用户问题
  ↓
CLI / FastAPI
  ↓
FAISS 向量召回
  ↓
候选片段排序、加权、来源均衡
  ↓
证据约束 Prompt
  ↓
Ollama 本地 LLM
  ↓
答案 + sources + 日志
```

### 2. 索引构建链路

```text
data/*.pdf / data/*.docx
  ↓
pdfplumber (表格→Markdown) / python-docx (表格→Markdown)
  ↓
clean_text()
  ↓
filter_documents() ← 过滤封面/目录/致谢/考题
  ↓
masker.py
  ↓
_protect_tables() ← 提取表格→占位符保护
  ↓
RecursiveCharacterTextSplitter（语义优先：章/节/条 > 段落 > 句子）
  ↓
_restore_tables() ← 还原 Markdown 表格
  ↓
enrich_chunk_metadata() + _build_chunk_prefix()
  ↓
OllamaEmbeddings(nomic-embed-text)
  ↓
faiss_index/
```

### 3. 技术栈

| 模块 | 技术 | 作用 |
|---|---|---|
| 文档解析 | `pdfplumber`、`python-docx`（表格转 Markdown）；降级回退 `pypdf`、`docx2txt` | 读取 PDF/DOCX 文本，自动检测并保留表格结构 |
| 文本切分 | `langchain-text-splitters` + 语义优先分隔符 | 在章/节/条边界断开，表格保护不拆散 |
| 入库过滤 | `filter_documents()` | 自动丢弃封面、目录、致谢、考题等低价值页面 |
| 脱敏 | `masker.py` 正则规则 | 保护手机号、身份证、邮箱、银行账号等字段 |
| 向量化 | Ollama `nomic-embed-text` | 生成 768 维文本向量；chunk 附带文档/章节前缀以增强区分度 |
| 向量库 | FAISS | 本地向量检索，当前唯一后端 |
| 检索增强 | 关键词重排 + 噪音过滤 + Query 改写 | 弥补纯语义检索不足，过滤目录页噪音，短问题自动扩展 |
| 生成模型 | Ollama `qwen2.5:7b` | 本地回答生成 |
| 答案校验 | `_verify_answer()` | 否定词反转自动检测并追加警告 |
| API 服务 | FastAPI + Uvicorn | Web/API 服务入口 |
| Web 页面 | `web/index.html` | 浏览器问答界面（Enter 提交、Alt+Enter 换行） |
| 评测系统 | `eval/run.py` + `eval/questions.jsonl` | 15 题自动化回归评测 |
| 日志 | JSONL | 记录问答与召回结果 |

### 4. 关键设计

- **本地优先**：模型、索引和日志均在本机运行，避免数据外传。
- **FAISS 单后端**：当前项目已移除 ChromaDB 分支，减少 Windows 环境下的不稳定因素和依赖体积。
- **证据溯源**：每次回答都返回 sources，避免只有结论没有依据。
- **文档均衡**：大 PDF chunk 数量多，检索时通过候选召回、权重和每文档上限控制来源占比。
- **混合检索**：FAISS 语义召回 + 关键词命中微调 + 噪音自动降权，保留固定 K 输出骨架。
- **表格感知**：PDF/DOCX 表格自动检测并转为 Markdown，LLM 可准确读取行列关系。
- **入库过滤**：封面、目录、致谢、考题等低价值页面在索引构建阶段即被丢弃。
- **Query 改写**：短问题自动扩展业务关键词，不调 LLM，零延迟。
- **答案校验**：自动检测否定词反转（"不得" → "可以"），追加校验警告。
- **索引 manifest**：记录知识源、切片参数、脱敏配置和 embedding 模型，便于判断索引是否过期。

## 三、项目结构

```text
md_transaction/
├── README.md              # 项目主文档：目标、架构、运行、维护
├── USER_GUIDE.md          # 用户指南：简介、使用方法、界面说明、常见问题
├── rag_app.py             # RAG 主链路：加载、清洗、过滤、脱敏、切片、检索、问答、校验
├── api_app.py             # FastAPI 接口层 + 一键启动入口
├── web/index.html         # Web 问答页面（Enter 提交、Alt+Enter 换行）
├── masker.py              # 数据脱敏模块
├── check_env.py           # 环境检查脚本
├── requirements.txt       # Python 依赖
├── data/                  # 知识源文档（PDF / DOCX）
├── eval/                  # 评测系统
│   ├── questions.jsonl    #   15 道固定测试题
│   └── run.py             #   自动化评测脚本
├── faiss_index/           # 自动生成的 FAISS 索引
└── logs/                  # 自动生成的问答日志
```

项目文档统一在 README.md 中维护。历史优化记录和工作记录已合并，不再单独维护。

## 四、环境准备

### 1. 基础要求

| 组件 | 要求 |
|---|---|
| Python | 3.10+ |
| Ollama | 已安装并可执行 `ollama list` |
| 生成模型 | `qwen2.5:7b` |
| 嵌入模型 | `nomic-embed-text` |
| 系统 | 当前按 Windows + PyCharm 虚拟环境验证 |

安装 Python 依赖：

```powershell
cd "D:\Project Repository\md_transaction"
python -m pip install -r requirements.txt
```

拉取 Ollama 模型：

```powershell
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
ollama list
```

如果执行 `ollama serve` 提示 `127.0.0.1:11434` 端口已占用，通常表示 Ollama 已经在后台运行，可直接继续使用。

### 2. 环境检查

```powershell
python check_env.py
```

检查内容包括：

- 当前 Python 解释器。
- 核心依赖是否可导入。
- Ollama 模型是否存在。
- `data/` 中是否存在 PDF/DOCX 知识源。
- FAISS 主链路依赖是否可用。

## 五、执行流程

### 1. 命令行问答

```powershell
cd "D:\Project Repository\md_transaction"
python check_env.py
python rag_app.py
```

首次运行时，如果 `faiss_index/` 不存在，程序会自动执行：

```text
文档加载（PDF表格→Markdown / DOCX表格→Markdown）
  → 文本清洗 → 低价值页面过滤 → 数据脱敏
  → 表格保护 → 语义分块 → chunk元数据增强+前缀
  → 向量化 → 构建 FAISS 索引
```

之后会进入交互模式：

```text
>>> 蒙东电力交易的中长期合约如何结算？
```

输入 `quit`、`exit` 或 `q` 退出。

### 2. Web/API 服务（一键启动）

```powershell
cd "D:\Project Repository\md_transaction"
python api_app.py
```

启动过程自动完成：
- **检测索引**：若 `faiss_index/` 不存在，自动从 `data/` 构建
- **预加载向量库**：服务启动即加载，首个请求无需等待
- **打开浏览器**：自动跳转 `http://127.0.0.1:8000/`

该终端需要保持打开。关闭终端后，Web 页面和 API 会停止响应。

> **高级用法**：如需手动控制端口或 host，仍可使用 `uvicorn api_app:app --host 127.0.0.1 --port 8000`。

### 3. API 调用

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/` | Web 问答页面 |
| `GET` | `/api/health` | 检查服务、索引和 Ollama 状态 |
| `GET` | `/api/index/status` | 查看索引文件、manifest 和召回参数 |
| `POST` | `/api/ask` | 提交问题并返回答案 |

`POST /api/ask` 示例：

```json
{
  "question": "蒙东电力交易的中长期合约如何结算？"
}
```

返回字段重点：

**顶层字段：**

| 字段 | 类型 | 含义 |
|---|---|---|
| `answer` | string | 模型生成的回答 |
| `sources` | array | 支撑回答的参考片段列表 |
| `ts` | string | 问答时间戳 |
| `model` | string | 当前使用的生成模型 |
| `embed_model` | string | 当前使用的嵌入模型 |
| `vector_backend` | string | 向量后端（当前固定为 faiss） |
| `retrieval_k` | int | 最终送入模型的片段数 |
| `candidate_k` | int | 初始候选召回数 |
| `max_chunks_per_source` | int | 每个文档最多保留片段数 |
| `prompt_version` | string | Prompt 版本标识 |

**sources[] 中各元素的字段：**

| 字段 | 含义 |
|---|---|
| `id` | 来源编号，如 S1、S2 |
| `rank` | 召回排序位置 |
| `filename` | 来源文件名 |
| `source` | 文件相对路径 |
| `page_label` | 页码或段落位置 |
| `section_title` | 章/节标题（自动提取） |
| `score` | 向量检索分数（FAISS 距离） |
| `chunk_id` | 片段唯一标识 |
| `excerpt` | 片段文本摘录（前 260 字） |

## 六、核心配置

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `RAG_LLM_MODEL` | `qwen2.5:7b` | 生成模型 |
| `RAG_EMBED_MODEL` | `nomic-embed-text` | 嵌入模型 |
| `RAG_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 地址 |
| `RAG_CHUNK_SIZE` | `650` | chunk 字符数 |
| `RAG_CHUNK_OVERLAP` | `100` | chunk 重叠字符数 |
| `RAG_RETRIEVAL_K` | `10` | 最终送入模型的片段数 |
| `RAG_CANDIDATE_K` | `120` | 初始候选召回数 |
| `RAG_MAX_CHUNKS_PER_SOURCE` | `5` | 每个文档最多保留片段数 |

文档权重位于 `rag_app.py` 的 `DOC_WEIGHTS`。当前用于提升规则汇编、培训教材等短文档进入最终上下文的机会。

## 七、数据与索引维护

### 1. 知识源目录

将知识源文件放入：

```text
data/
```

当前支持：

- PDF
- DOCX

### 2. 何时需要重建索引

以下情况必须重建 `faiss_index/`：

- 新增、删除、替换知识源文件。
- 修改 `RAG_CHUNK_SIZE` 或 `RAG_CHUNK_OVERLAP`。
- 修改 `masker.py` 中的脱敏配置。
- 更换 `RAG_EMBED_MODEL`。
- 修改索引构建逻辑。

重建方式：

```powershell
Remove-Item -Recurse -Force faiss_index
python api_app.py
```

### 3. 生成物说明

| 目录 | 说明 |
|---|---|
| `faiss_index/` | 自动生成的向量索引，不作为源码维护 |
| `logs/` | 自动生成的问答日志 |
| `__pycache__/` | Python 缓存 |

不要加载来源不明的 `faiss_index/index.pkl`。FAISS 的本地索引包含 pickle 文件，只应使用本项目本机生成的可信索引。

## 八、脱敏策略

脱敏配置位于 `masker.py` 的 `MASK_CONFIG`。

当前策略：

| 类型 | 当前处理 |
|---|---|
| 手机号、身份证、邮箱、银行账号、统一社会信用代码 | 默认脱敏 |
| 金额、电价、电量、公司名、地址、人名 | 默认保留 |

这样做是为了保护强隐私字段，同时保留电力交易规则问答所需的业务数字和主体信息。若知识源换成合同、客户资料或交易流水，应重新评估脱敏策略。

预览脱敏效果：

```powershell
python masker.py --preview data/
```

## 九、项目路线

### 已完成

- 本地 RAG 主链路。
- FAISS 向量索引。
- PDF/DOCX 表格感知解析（pdfplumber / python-docx → Markdown）。
- 文本清洗和脱敏。
- 低价值页面入库前过滤（封面、目录、致谢、考题）。
- 语义优先分块（章/节/条边界）+ 表格保护性切分。
- Chunk 上下文前缀（文件名 + 章节路径）。
- 混合检索：关键词重排 + 噪音降权 + 文档均衡。
- Query 改写（短问题自动扩展业务术语）。
- 答案校验（否定词反转自动检测 + 警告）。
- 证据约束 Prompt v4（适配 qwen2.5:7b）。
- CLI 问答 + FastAPI Web/API 一键启动。
- 问答日志追踪。
- 评测系统（15 题 + `python eval/run.py` 自动化回归）。
- Web 页面（Enter 提交、章节定位显示、星级评分）。

### 短期优化

- 引入 BM25 或关键词召回，与向量召回做融合。
- 引入 Cross-Encoder Reranker，进一步提高 sources 精度。
- 增加客户反馈字段，如”有用/无用/答非所问”。

### 中期优化

- 引入 Cross-Encoder Reranker，进一步提高 sources 精度。
- 根据问题类型动态调整来源权重。
- 多知识库、多业务域切换。

### 长期优化

- 建立标准评测报告，比较不同模型、切片参数和召回策略。
- 接入企业内部系统（企业微信、OA 等）。
- 增加权限控制、审计日志和部署脚本。
- Docker 容器化部署。

## 十、常见问题

### 1. `ollama serve` 提示端口占用

通常是 Ollama 已经启动。可用以下命令确认模型是否可用：

```powershell
ollama list
```

### 2. 页面打不开

确认服务是否已启动（推荐一键启动）：

```powershell
python api_app.py
```

或手动启动：

```powershell
uvicorn api_app:app --host 127.0.0.1 --port 8000
```

访问：

```text
http://127.0.0.1:8000/
```

### 3. 修改文档后回答没变化

原因通常是旧索引仍在使用。删除 `faiss_index/` 后重新运行：

```powershell
Remove-Item -Recurse -Force faiss_index
python api_app.py
```

### 4. 回答不准确

优先检查：

- `logs/rag_trace.jsonl` 中召回的 sources 是否相关。
- 问题是否过于宽泛。
- 知识源中是否真的存在直接依据。
- 是否需要调整 chunk 参数或文档权重。
- 答案是否触发了校验警告（⚠️ 自动校验提示）。
- 运行 `python eval/run.py` 做系统性回归评测。

### 5. 默认 Python 缺少依赖

项目建议使用 PyCharm 虚拟环境。先确认当前解释器：

```powershell
python -c "import sys; print(sys.executable)"
```

## 十一、接手建议

新接手本项目时，建议按以下顺序理解：

1. 先读 `README.md`，确认项目目标和运行方式。
2. 运行 `python check_env.py`，确认环境和模型。
3. 运行 `python api_app.py`，启动服务并体验 Web 问答（首次运行会自动构建索引）。
4. 阅读 `rag_app.py`，理解主链路（加载→过滤→脱敏→分块→检索→校验）。
5. 阅读 `api_app.py`，理解接口封装和一键启动逻辑。
6. 阅读 `masker.py`，确认脱敏策略是否符合当前数据。
7. 查看 `logs/rag_trace.jsonl`，用真实问题判断召回和回答质量。
8. 运行 `python eval/run.py`，了解当前评测基准和通过率。

如果要继续优化，优先考虑换用更大模型和引入 Cross-Encoder Reranker。

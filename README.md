# MD Transaction RAG 知识库

本项目是一个本地化电力交易规则问答系统。它将蒙东电力交易相关 PDF/DOCX 文档构建为本地向量知识库，通过 Ollama 本地模型完成检索增强问答，并在回答中返回来源片段、页码、score 和 chunk_id，便于追溯依据。

项目目标不是做一个通用聊天机器人，而是服务于电力交易规则查询、培训材料检索、政策依据定位和客户问答接口演示。数据、向量索引、问答日志均保留在本机。

---

## 目录

- [一、项目任务](#一项目任务)
- [二、技术架构](#二技术架构)
- [三、项目结构](#三项目结构)
- [四、环境准备](#四环境准备)
- [五、执行流程](#五执行流程)
- [六、核心配置](#六核心配置)
- [七、数据与索引维护](#七数据与索引维护)
- [八、脱敏策略](#八脱敏策略)
- [九、项目路线](#九项目路线)
- [十、常见问题](#十常见问题)
- [十一、接手建议](#十一接手建议)
- [十二、技术深潜](#十二技术深潜)
- [十三、打包交付方案](#十三打包交付方案)

---

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

---

## 二、技术架构

### 1. 总体链路

```text
用户问题
  ↓
Query 改写（短问题自动扩展业务关键词，零延迟）
  ↓
FAISS 向量召回（CANDIDATE_K=120 初筛）
  ↓
候选片段排序、文档权重加权、关键词重排、噪音降权
  ↓
来源均衡（每个文档最多 MAX_CHUNKS_PER_SOURCE=5 个片段）
  ↓
定长截断（RETRIEVAL_K=10 送入模型）
  ↓
证据约束 Prompt 组装
  ↓
Ollama 本地 LLM（qwen2.5:7b, temperature=0.1, context=8192）
  ↓
答案校验（否定词反转检测）
  ↓
答案 + sources + JSONL 日志
```

### 2. 索引构建链路

```text
data/*.pdf / data/*.docx
  ↓
pdfplumber (表格→Markdown) / python-docx (表格→Markdown)
  ↓ (降级回退: pypdf / docx2txt)
clean_text() — 清除 \x00-\x1f 控制字符、� 替换字符、压缩空白
  ↓
filter_documents() — 过滤封面/目录/致谢/考题等低价值页面
  ↓ (判断条件: 文本<30字 | 首行为目录/前言/致谢 | 选择题≥6个 | 数字占比>85%)
masker.py — 正则脱敏（手机号、身份证、邮箱、银行账号等）
  ↓
_protect_tables() — 正则提取 Markdown 表格 → 占位符 <!--TBL_N--> 保护
  ↓
RecursiveCharacterTextSplitter（语义优先分隔符层级）
  ↓  分隔符优先级: \n第 → Markdown标题 → 中文序号 → 段落 → 句子 → 空格
_restore_tables() — 占位符还原为 Markdown 表格
  ↓
enrich_chunk_metadata() — 生成 chunk_id / 提取章节标题 / 添加 doc_id
  ↓
_build_chunk_prefix() — 为每个 chunk 添加 [文件名] [章节路径] 前缀 → embedding
  ↓
OllamaEmbeddings(nomic-embed-text) — 逐条 HTTP POST 到 Ollama, 768维向量
  ↓
FAISS.from_documents() → faiss_index/index.faiss + index.pkl
  ↓
write_index_manifest() → faiss_index/manifest.json
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

---

## 三、项目结构

```text
md_transaction/
├── README.md              # 项目主文档：目标、架构、运行、维护、技术深潜
├── USER_GUIDE.md          # 用户指南：简介、使用方法、界面说明、常见问题
├── rag_app.py             # RAG 主链路：加载、清洗、过滤、脱敏、切片、检索、问答、校验
├── api_app.py             # FastAPI 接口层 + 一键启动入口（含索引自动构建）
├── masker.py              # 数据脱敏模块（纯正则，12条规则，按序执行）
├── check_env.py           # 环境检查脚本（Python版本/依赖/Ollama模型/知识源文件）
├── requirements.txt       # Python 依赖
├── web/
│   └── index.html         # Web 问答页面（Enter 提交、Alt+Enter 换行、星级评分、来源面板）
├── data/                  # 知识源文档（PDF / DOCX）
├── eval/                  # 评测系统
│   ├── questions.jsonl    #   15 道固定测试题（覆盖结算/注册/申报/价格/否定词/不可回答等）
│   └── run.py             #   自动化评测脚本（支持 --rebuild 重建索引）
├── faiss_index/           # 自动生成的 FAISS 索引（index.faiss, index.pkl, manifest.json）
└── logs/                  # 自动生成的问答日志（rag_trace.jsonl）
```

---

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

---

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

---

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

| 文档 | 权重 | 理由 |
|---|---|---|
| `蒙东新能源电站交易规则汇编_AI算法开发版.docx` | 1.40 | 规则汇编，权威性最高 |
| `蒙东电力交易市场交易员培训教材.pdf` | 1.25 | 培训教材，结构化好 |
| `20251021010756789.pdf` | 1.00 | 默认权重（基准） |

---

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
| `faiss_index/` | 自动生成的向量索引（index.faiss + index.pkl + manifest.json），不作为源码维护 |
| `logs/` | 自动生成的问答日志 |
| `__pycache__/` | Python 缓存 |

> ⚠️ **安全警告**：不要加载来源不明的 `faiss_index/index.pkl`。FAISS 的本地索引包含 pickle 文件，只应使用本项目本机生成的可信索引。

---

## 八、脱敏策略

脱敏配置位于 `masker.py` 的 `MASK_CONFIG`。

### 规则执行顺序

脱敏按以下顺序层层递进，每一步的输出是下一步的输入：

| 顺序 | 规则名称 | 类型 |
|---|---|---|
| 1 | `phone` | 结构化数据 |
| 2 | `id_card` | 结构化数据 |
| 3 | `credit_code` | 结构化数据（含白名单） |
| 4 | `email` | 结构化数据 |
| 5 | `bank_account` | 结构化数据 |
| 6 | `ip` | 结构化数据 |
| 7 | `amount` | 数值模糊（在 company_name 前，避免公司名含数字被误伤） |
| 8 | `company_name` | 实体名称 |
| 9 | `address` | 实体名称 |
| 10 | `person_name` | 实体名称（实验性） |
| 11 | `price` | 数值模糊 |
| 12 | `quantity` | 数值模糊 |

### 当前策略

| 类型 | 当前处理 | 原因 |
|---|---|---|
| 手机号、身份证、邮箱、银行账号、统一社会信用代码 | **默认脱敏** | 强隐私字段，不可保留 |
| IP 地址 | 默认不脱敏 | 业务文档中不常见 |
| 金额、电价、电量、公司名、地址、人名 | **默认保留** | 电力交易规则问答需保留业务数字和主体信息 |

这样做是为了保护强隐私字段，同时保留电力交易规则问答所需的业务数字和主体信息。若知识源换成合同、客户资料或交易流水，应重新评估脱敏策略。

### 脱敏效果预览

```powershell
python masker.py --preview data/
```

---

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
- 增加客户反馈字段，如"有用/无用/答非所问"。

### 中期优化

- 根据问题类型动态调整来源权重。
- 多知识库、多业务域切换。

### 长期优化

- 建立标准评测报告，比较不同模型、切片参数和召回策略。
- 接入企业内部系统（企业微信、OA 等）。
- 增加权限控制、审计日志和部署脚本。
- Docker 容器化部署。

---

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

---

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

---

## 十二、技术深潜

> 本章为架构师和接手开发人员提供逐一模块的深度剖析，涵盖算法细节、数据结构、设计考量和边界处理。读完本章后应能完全掌握项目内部机制，具备独立维护和二次开发能力。

---

### 12.1 文档加载层（`_load_pdf_pages` / `_load_docx_sections`）

#### PDF 解析链路

```
文件 → pdfplumber.open()
       ├── 逐页遍历 page.extract_text() → 文本
       ├── page.extract_tables() → 二维数组
       │     └── _table_to_markdown() → Markdown 表格块
       │           规则: 清洗 None→"" | 换行→空格 | 管道符→转义
       │                 空行剔除 | 列宽对齐 | 生成 |---|---| 分隔行
       └── 文本 + "\n\n" + Markdown表格 → Document(page_content, metadata)
            metadata: { page, has_tables, table_count, filename, doc_type, source }
```

**降级策略**：若 `pdfplumber.open()` 抛出异常（如加密 PDF、损坏文件），自动回退到 `PyPDFLoader`。PyPDFLoader 不做表格检测，输出纯文本。

**表格转 Markdown 算法**（`_table_to_markdown`）：

1. 遍历每行，清洗每个 cell：`None→""`、`strip()`、`\n→" "`、`|→"\|"`
2. 过滤掉全空行
3. 计算最大列数，补齐不足列的行（填 `""`）
4. 第一行作为表头，生成 `| A | B | C |` 格式
5. 第二行生成分隔线 `| --- | --- | --- |`
6. 剩余行作为数据行

```python
# _table_to_markdown 的输入输出示例
输入: [["名称", "价格"], ["风电", "0.3元/kWh"]]
输出:
| 名称 | 价格 |
| --- | --- |
| 风电 | 0.3元/kWh |
```

#### DOCX 解析链路

```
文件 → python-docx Document
       └── 遍历 doc.element.body 的子元素
             ├── w:p 标签 → 查找段落 → 提取文本
             └── w:tbl 标签 → 查找表格 → 逐行逐cell提取
                  └── 清洗: strip(), \n→空格, |→转义
       → 按原始交错顺序组装 parts 列表
         例: [("text", "段落1"), ("table", [[...]]), ("text", "段落2")]
       → "\n\n".join(blocks) → Document(page_content)
          metadata: { has_tables, table_count }
```

**降级策略**：若 `python-docx` 不可用，回退到 `Docx2txtLoader`（纯文本提取，无表格结构）。

**设计要点**：DOCX 加载器保留了段落和表格在文档中的原始交错顺序，这对规则类文档至关重要——某条规定可能由"一段说明 + 一张参数表 + 一段注释"组成，顺序丢失会导致语义断裂。

---

### 12.2 文本清洗层（`clean_text`）

```text
原始 PDF 文本
  ↓
CONTROL_CHARS_RE.sub(" ", text)      # 将 \x00-\x08 \x0b\x0c \x0e-\x1f \x7f 替换为空格
  ↓
text.replace("�", " ")          # 替换 Unicode 替换字符 (�)
  ↓
逐行处理:
  - re.sub(r"[ \t]+", " ", raw)      # 压缩连续空白为单个空格
  - strip()                          # 去除首尾空白
  - 过滤空行
  ↓
"\n".join(lines)                     # 重新拼接
```

这一步解决了 PDF 抽取中的三个典型问题：
1. **控制字符污染**：PDF 内部标记（如 `\x0c` 换页符）混入文本，污染 embedding
2. **替换字符**：`�` 是 PDF 无法解码某字符时的占位符，对语义检索无意义
3. **异常空白**：PDF 排版产生的多余空格和 Tab 会干扰分词和 embedding 质量

---

### 12.3 低价值页面过滤层（`filter_documents`）

过滤规则通过 `_is_low_value_page()` 实现，四条规则按优先级检测：

| # | 规则 | 阈值 | 目标 |
|---|---|---|---|
| 1 | 文本长度过短 | `< 30` 字符 | 封面、空白页、分隔页 |
| 2 | 首行命中已知签名 | 匹配列表中的字符串 | 目录、前言、致谢、参考文献、附录、声明 |
| 3 | 选择题选项密度过高 | 选项匹配 `≥ 6` 个 | 考题页（A. B. C. D. 模式） |
| 4 | 数字/标点占比过高 | `> 85%` 且文本 `< 200` 字 | 纯页码行、点线目录 |

**已知签名列表**（`_LOW_VALUE_SIGNATURES`）：
- 目录/目  录/CONTENTS/Table of Contents
- 前言/序言/绪论/引言
- 致谢/鸣谢/ACKNOWLEDGEMENTS
- 参考文献/参考资料/References
- 附录/Appendix
- 声明/免责声明/Disclaimer

**考题检测正则**：`[A-D][．.。、]\s*\S` —— 匹配 A. B． C、 D。等选择题选项标记

**为什么要入库前过滤而非检索时降权？**
- 入库前过滤减少索引体积，加快检索速度
- 封面和目录页即使被召回也不含有效规则信息
- 考题页会干扰规则类问答（模型可能把题目当规则引用）

---

### 12.4 脱敏模块（`masker.py`）

#### 架构设计

```
MASK_CONFIG (开关字典)
     ↓
RULE_ORDER (执行顺序列表)
     ↓
MASK_RULES (规则函数注册表) → 逐个执行启用的规则
     ↓
mask_text(text, config) → 脱敏后文本
```

每条规则都是一个纯函数 `f(text: str) -> str`，接受文本返回处理后的文本。规则串联执行时，后一条规则的输入是前一条的输出，因此顺序至关重要。

#### 白名单机制

`WHITELIST` 列表中的机构名会跳过脱敏：

```python
WHITELIST = [
    "国家发展改革委",
    "国家能源局",
    "蒙东电力交易中心",
    "国家电网",
    "南方电网",
    "内蒙古电力",
]
```

白名单在 `_mask_credit_code` 和 `_mask_company_name` 中生效——若文本包含白名单实体，整段跳过该规则的脱敏。

#### 各规则详解

| 规则 | 正则要点 | 脱敏效果示例 |
|---|---|---|
| `phone` | `1[3-9]\d[ -]?\d{4}[ -]?\d{4}` + 座机号 `\d{3,4}[ -]\d{7,8}` | `13812345678` → `138****5678` |
| `id_card` | 6位地区码+年份(19\|20)+月日+3位顺序码+校验码 | `150102199001011234` → `150102********1234` |
| `credit_code` | 18位 `[0-9A-HJ-NPQRTUWXY]`，含白名单排除 | `91150000MA0XXXXX00` → `9115**********XX00` |
| `email` | 用户名+`@`+域名 | `zhangsan@company.com` → `z**n@company.com` |
| `bank_account` | 16-19位连续数字 | `6222021234567890123` → `****0123` |
| `ip` | 四段0-255的IPv4 | `192.168.1.100` → `192.*.*.100` |
| `amount` | 数字+元/万元/美元/欧元（默认关闭） | `500万元` → `***万元` |
| `company_name` | 前导边界+2-30字+公司后缀（默认关闭） | `XX新能源有限公司` → `X***司` |
| `address` | 省+市+区县+街道/路/号（默认关闭） | `内蒙古自治区通辽市XX旗XX路10号` → `内蒙古自治区***` |
| `person_name` | 常见姓氏+1-2字名+上下文标记（默认关闭） | `由张三负责` → `由张*负责` |
| `price` | 数字+元/MWh等电价单位（默认关闭） | `0.2829元/kWh` → `[0-1]元/kWh` |
| `quantity` | 数字+万千瓦时/MWh等电量单位（默认关闭） | `50000万千瓦时` → `约5万千瓦时` |

---

### 12.5 语义分块层（`split_documents`）

#### 表格保护机制

分块前须保护 Markdown 表格不被切割。表格在语义上是不可分的原子单元——一个结算参数表被切成两半，前半在 chunk A、后半在 chunk B，模型将无法理解完整规则。

**保护算法**（三步走）：

```
步骤1: _protect_tables(text)
  ├── 正则匹配 Markdown 表格: (\|[^\n]+\|\n\|[-\s|:]+\|\n(?:\|[^\n]*\|\n?)+)
  │    结构: 表头行 | 分隔行 | 数据行(可多行)
  ├── 将每张表格存入 all_tables 列表
  └── 在原文本中用占位符替换: <!--TBL_0-->  <!--TBL_1-->  ...

步骤2: RecursiveCharacterTextSplitter.split_documents(docs)
  └── 占位符是普通文本，不会被切割

步骤3: _restore_tables(chunks, all_tables)
  ├── 遍历每个 chunk
  └── 将占位符还原为原始 Markdown 表格
```

**表格匹配正则分析**：

```python
_TABLE_RE = re.compile(
    r"(\|[^\n]+\|\n"          # 表头行: | xxx | ... |\n
    r"\|[-\s|:]+\|\n"          # 分隔行: | --- | :--- | ... |\n
    r"(?:\|[^\n]*\|\n?)+)",    # 数据行: | xxx | ... |\n (至少一行)
    re.MULTILINE,
)
```

#### 分隔符层级

`RecursiveCharacterTextSplitter` 按以下优先级尝试断句：

```
优先级 1: "\n第"                    # 第X章 / 第X节 / 第X条 — 法律/规则文档的结构边界
优先级 2: "\n# "  "\n## "          # Markdown 标题
优先级 3: "\n一、" "\n二、" ... "\n十、"   # 中文序号段落
优先级 4: "\n\n"  "\n"             # 自然段落边界
优先级 5: "。"  "；"  "！"  "？"   # 句子边界
优先级 6: ". "  "; "               # 英文句子边界
优先级 7: " "  ""                  # 最后手段：按空格或字符硬切
```

**为什么 `"\n第"` 优先级最高？**

电力交易规则文档的法定结构是"第X章 → 第X节 → 第X条"。在"第"字前断开，每个 chunk 恰好包含一条完整规则，避免把"第三条（某某规定）"切成两段。这是为电力规则类文档定制的，通用文档可能不适用。

#### Chunk 元数据增强（`enrich_chunk_metadata`）

每个 chunk 被赋予以下元数据：

| 字段 | 生成方式 | 示例 |
|---|---|---|
| `chunk_id` | `{doc_slug}_p{page}_{index:03d}_{md5[:8]}` | `md_training_p3_002_a1b2c3d4` |
| `doc_id` | `_safe_slug(filename)` — 仅保留字母数字和中文 | `md_training` |
| `filename` | 原始文件名 | `蒙东电力交易市场交易员培训教材.pdf` |
| `page_label` | PDF页码+1（pdfplumber页码从0开始） | `4` |
| `section_title` | `_guess_section_title()` 自动提取 | `第三章 市场注册 ▸ 第二节 注册流程` |
| `text_hash` | page_content 的 MD5 前8位 | `a1b2c3d4` |
| `chunk_index` | 同文档同页的序号 | `2` |

#### 章节标题提取（`_guess_section_title`）

```
优先级1: 第X章 + 第X节 + 第X条 → 以 "  ▸  " 串联，多层命中累加
  例: "第三章 市场注册  ▸  第二节 注册流程  ▸  第九条"

优先级2: 中文数字编号（一、二、三、...）+ 短行（≤50字）

优先级3: 业务关键词行（≤35字且包含"市场/交易/结算/注册/申报/价格/保量/中长期/现货/合约/电量/电价/规则/流程/条件/方式/机制/主体"）
```

章节标题用于：
- Chunk 上下文前缀（帮助 embedding 区分不同章节的相似段落）
- 来源定位（前端显示"第三章 市场注册 | p.12"）
- 日志追踪

#### Chunk 上下文前缀（`_build_chunk_prefix`）

```
"[蒙东电力交易市场交易员培训教材.pdf] [第三章 市场注册  ▸  第二节 注册流程]\n"
+ 原始 chunk 文本
```

此前缀**仅用于 embedding 向量计算**，不污染最终展示给 LLM 的文本。原理：两个不同文档中关于"注册条件"的段落语义相似但来源不同——加上文件名和章节前缀后，embedding 能区分"培训教材第三章的注册条件"和"规则汇编第五章的注册条件"，避免 FAISS 将它们混为一谈。

---

### 12.6 向量化层（`OllamaEmbeddings`）

#### 为什么自定义 Embeddings 类

LangChain 社区版的 `OllamaEmbeddings` 依赖 `sentence-transformers` 和 PyTorch（约 2GB），在 Windows 环境下安装复杂且不稳定。本项目直接封装 Ollama HTTP API，完全绕开 PyTorch：

```python
class OllamaEmbeddings(Embeddings):
    """
    每次调用 embed_documents / embed_query 时:
    1. POST http://localhost:11434/api/embeddings
    2. Body: {"model": "nomic-embed-text", "prompt": text}
    3. 返回 768 维 float 列表
    """
```

**关键参数**：
- API 端点：`POST /api/embeddings`
- 模型：`nomic-embed-text`（Nomic AI 开源的文本嵌入模型）
- 向量维度：768
- 调用方式：逐条调用（`for text in texts`），非批量。这是 Ollama API 的限制——`/api/embeddings` 端点不接受文本数组

**性能考量**：逐条调用的延迟与文本数量线性相关。构建索引时，若有 N 个 chunk，则需要 N 次 HTTP 往返。对于数百个 chunk 的规模（本项目典型值 200-500），耗时在 1-3 分钟，可接受。

---

### 12.7 FAISS 向量存储（`build_faiss_vectorstore` / `load_faiss_vectorstore`）

#### 索引文件结构

```
faiss_index/
├── index.faiss    # FAISS 二进制索引文件（存储向量和近邻图结构）
├── index.pkl      # Python pickle 文件（存储 docstore: {id → Document} 和 index→docstore_id 映射）
└── manifest.json  # 索引构建参数快照（用于过期检测）
```

#### IndexFlatL2 距离

FAISS 默认使用 `IndexFlatL2`（欧几里得距离），距离越小表示语义越相似。ChromaDB 默认用余弦相似度（越大越相似），两者方向相反。本项目在检索排序和分数显示中统一按"越小越好"处理。

#### 索引过期检测（`warn_if_index_stale`）

```
加载索引时:
  saved_manifest  ← 读取 faiss_index/manifest.json
  current_manifest ← 实时计算 current_index_manifest()

  _manifest_diff(saved, current) 检测以下字段是否变化:
    - ingest_version  (索引构建代码版本)
    - embed_model     (如从 nomic-embed-text 换成其他)
    - chunk_size / chunk_overlap
    - mask_config_hash (脱敏配置的 SHA256 前12位)
    - data_files      (文件列表 + 大小 + 修改时间 + SHA256)

  若有变化 → 打印 [WARN] cached index may be stale
```

**`data_files` 的对比逻辑**：每个文件记录 `{path, size, mtime_ns, sha256}` 四个维度，任一不同即判定变化。SHA256 采用流式读取（1MB 分块），避免大文件一次性加载到内存。

---

### 12.8 检索增强层（`_retrieve`）

这是整个系统最核心的模块，在标准 FAISS 语义检索之上叠加了三层增强。

#### 完整检索流程

```
Step 0: Query 改写 (_rewrite_query)
  ├── question >= 25 字符 → 直接使用原问题
  └── question < 25 字符 → 匹配 _QUERY_EXPANSIONS 词典扩展
      例: "结算" → "结算 结算方式 结算周期 结算电量 结算价格 电费结算"

Step 1: 候选召回
  └── vectorstore.similarity_search_with_score(rewritten_query, k=CANDIDATE_K=120)

Step 2: 逐条打分增强
  对每条候选结果:
    ├── base_score = FAISS L2 距离（越小越好）
    ├── weight = DOC_WEIGHTS 中匹配的文件权重（无匹配则 1.0）
    ├── adjusted_score = base_score / weight          # 高权重文档分数变小（排前）
    ├── kw_rel = _keyword_relevance(query, text)      # 关键词重叠度 0-1
    ├── adjusted_score *= (1.0 - kw_rel * 0.30)       # 关键词匹配的排前（最多影响30%）
    ├── if _is_noise_chunk(text):                      # 低价值chunk检测
    │       adjusted_score *= 2.5                      # 严重降权
    └── 记录 {doc, score, source, adjusted_score}

Step 3: 排序
  └── ranked.sort(key=lambda x: x["adjusted_score"])  # 升序（越小越好）

Step 4: 来源均衡 — 第一轮
  ├── 遍历 ranked 列表
  ├── 每个文档最多选 MAX_CHUNKS_PER_SOURCE=5 个
  ├── 选中后 source_counts[src]++
  └── 达到 RETRIEVAL_K=10 时停止

Step 5: 补齐 — 第二轮
  └── 如果第一轮不足 10 个，跳过来源限制继续选
```

#### 关键词相关性（`_keyword_relevance`）

```python
def _keyword_relevance(query: str, text: str) -> float:
    # 提取 query 中的 2-4 字中文词组 和 2+ 字母英文单词
    terms = re.findall(r"[一-鿿]{2,4}|[a-zA-Z]{2,}", query)
    if not terms:
        return 0.5
    # 计算在 chunk 中的命中率
    hits = sum(1 for t in terms if t.lower() in text.lower())
    return hits / len(terms)
```

**为什么最多影响 30%？** `adjusted_score *= (1.0 - kw_rel * 0.30)` 的设计意图是：关键词匹配作为语义检索的微调补充，而非替代。纯关键词检索容易因"结算"一词出现在目录页而把目录排到第一；限制在 30% 确保语义相似度仍是主导信号。

#### 噪音检测（`_is_noise_chunk`）

```python
def _is_noise_chunk(text: str) -> bool:
    # 1. 文本过短 (< 60字)
    if len(text.strip()) < 60: return True
    # 2. 首行为目录/前言/致谢
    if any(kw in first_line for kw in (...)): return True
    # 3. 点线连接过多 (> 20个点 且 < 500字) — 目录特征
    if dots > 20 and len(text) < 500: return True
    # 4. 数字/标点占比 > 70%
    if num_blank_ratio > 0.7: return True
```

**降权系数 2.5** 意味着噪音 chunk 排在所有正常 chunk 之后，除非正常 chunk 已用完。

#### 文档均衡数学原理

设某大 PDF 有 700 页、被切成 350 个 chunk，小汇编有 30 页、被切成 15 个 chunk。若不设 `MAX_CHUNKS_PER_SOURCE` 限制，`top-10` 很可能全部来自大 PDF，小汇编的权威规则无法进入上下文。

```
无均衡:    top-10 = [大PDF×10]                    → 上下文完全被大文档垄断
设上限=5:  top-10 = [大PDF×5, 小汇编×5]            → 多种来源进入上下文
设上限+权重: top-10 = [小汇编×5(权1.40), 大PDF×3, 培训教材×2(权1.25)]
```

---

### 12.9 Query 改写（`_rewrite_query`）

#### 触发条件

```python
if len(question) >= 25:
    return question  # 信息量已足够，不改写
```

短问题如"怎么结算？"只有 5 个字符，语义检索可能找不到足够匹配的 chunk。改写为"怎么结算 结算方式 结算周期 结算电量 结算价格 电费结算"后，维度更丰富。

#### 扩展词典（`_QUERY_EXPANSIONS`）

| 触发词 | 扩展词 |
|---|---|
| 结算 | 结算方式 结算周期 结算电量 结算价格 电费结算 |
| 注册 | 市场注册 注册流程 注册条件 注册材料 市场主体注册 |
| 申报 | 申报流程 申报时间 申报要求 申报材料 交易申报 |
| 中长期 | 中长期合约 中长期交易 中长期结算 年度合约 月度合约 |
| 现货 | 现货交易 现货市场 日前市场 日内市场 实时市场 |
| 价格 | 电价 限价 出清价格 合约价格 度电价格 |
| 电量 | 交易电量 结算电量 申报电量 保量保价 |
| 考核 | 偏差考核 免考核 考核标准 考核费用 |
| 合同 | 入市协议 购售电合同 输配电合同 |
| 偏差 | 偏差电量 偏差考核 偏差结算 正偏差 负偏差 |

**设计原则**：不调 LLM，零延迟。扩展词来自业务领域知识，是手工维护的、确定性的映射表，而非从 embedding 或本体库自动生成。

---

### 12.10 Prompt 工程（`RAG_PROMPT`）

当前版本 `rag_prompt_v4_qwen` 针对 qwen2.5:7b 做了专门适配。

#### 结构分析

```
SYSTEM ROLE: "你是蒙东新能源电站交易规则本地知识库问答助手。"

约束1 — 依据限制:
  "只能依据【参考片段】回答，不得编造未出现在片段中的规则、数值或流程"
  "Markdown 表格需逐列对应读取，不得混淆行列关系"
  → 防止幻觉和表格误读

约束2 — 引用标注:
  "涉及规则、时间、价格、电量、结算、主体条件时，必须在句末标注来源编号"
  "数值必须与片段中的数字完全一致，不得四舍五入或近似"
  → 强制溯源和数值保真

约束3 — 拒答机制:
  "如果参考片段不足以回答，请明确说：当前知识库未检索到足够依据"
  → 防止强行编造答案

约束4 — 否定词保护:
  "涉及不得、不结转、除外、应当、必须、不得超过、按月、按日等规则词时，不得反向改写原文含义"
  → 防止 180° 反转规则含义

约束5 — 冲突处理:
  "当多个来源的规则存在差异时，优先采信正式规则文件，并在注意事项中说明差异"
  → 处理规则矛盾

约束6 — 条件保留:
  "条件性规则（如...则...）需完整保留条件和结论，不可省略前提"
  → 防止断章取义

约束7 — 风格:
  "表达简洁专业，适合电力交易员阅读"

输出格式:
  一、结论（简明直接回答用户问题）
  二、依据（逐条列出支撑结论的规则原文，标注 [Sx]）
  三、注意事项（规则适用的前置条件、例外情形、常见误解）
```

#### 生成参数

```python
options = {
    "temperature": 0.1,  # 低温度确保事实性问题的确定性输出
    "top_p": 0.9,        # 核采样
    "num_ctx": 8192,     # 上下文窗口：容纳 ~10 个 chunk (每个约650字) + prompt + 回答
}
```

**为什么 temperature=0.1？** 电力规则问答不需要创意——同一个问题每次都应得到相同答案。低温度最大程度减少模型的随机性，确保输出稳定可复现。

---

### 12.11 答案校验（`_verify_answer`）

#### 否定词反转检测

核心思路：如果来源片段中有否定/限制词但回答中消失了，说明模型可能在回答时做了"正面改写"。

```python
_NEGATION_PAIRS = [
    ("不得", "可以"),       # 原文"不得参与" → 回答"可以参与" → 危险
    ("不应", "应该"),
    ("不结转", "结转"),
    ("禁止", "允许"),
    ("除外", "包括"),
    ("不予", "予以"),
    ("不得参与", "可以参与"),
    ("不能", "可以"),
]
```

**检测算法**：

```
1. 合并所有 sources 的 excerpt 为 source_text
2. 对每一对 (prohibited, allowed):
     if prohibited in source_text:                    # 原文含否定词
         if allowed in answer and prohibited not in answer:  # 回答含肯定词但缺失否定词
             追加警告: "原文含「{prohibited}」，回答中未出现，请以原文为准"
3. 将警告追加到 answer 末尾（最多3条）
```

**局限性**：这是基于字符串匹配的浅层校验，不涉及语义理解。无法检测更隐蔽的信息扭曲——如数值被改动、条件被省略、上下文被剥离等。因此它仅作为补充性的安全网，不能替代人工审核。

---

### 12.12 Web 前端（`web/index.html`）

#### 布局架构

```
┌─────────────────────────────────────────────────────┐
│ Header: ⚡ MD Transaction RAG  |  ● 服务正常          │
├──────────────────────────────┬──────────────────────┤
│                              │  📎 参考片段 (N 条)   │
│   📝 回答                     │  ┌────────────────┐  │
│                              │  │ S1 文件.pdf     │  │
│   一、结论                    │  │ 📍 第三章 | p.4 │  │
│   ...                        │  │ ★★★★☆           │  │
│   二、依据                    │  │ 文本摘录...      │  │
│   [S1] ...                   │  └────────────────┘  │
│   三、注意事项                │  ┌────────────────┐  │
│   ...                        │  │ S2 ...           │  │
│                              │  └────────────────┘  │
├──────────────────────────────┴──────────────────────┤
│ [输入框：Enter提交 / Alt+Enter换行]      [提问]      │
└─────────────────────────────────────────────────────┘
```

#### 键盘交互

- **Enter**：提交问题（preventDefault + requestSubmit）
- **Alt+Enter / Shift+Enter / Ctrl+Enter**：默认行为（换行）
- textarea 自动高度调整（`scrollHeight`），最大 160px

#### FAISS 分数 → 星级映射

```javascript
function formatScore(score) {
    if (score <= 0.15) return "★★★★★";  // 极相似
    if (score <= 0.35) return "★★★★☆";  // 相似
    if (score <= 0.60) return "★★★☆☆";  // 较相似
    if (score <= 1.00) return "★★☆☆☆";  // 弱相似
    return "★☆☆☆☆";                      // 远
}
```

#### XSS 防护

所有用户输入和 API 返回的动态内容通过 `escapeHtml()` 函数转义，覆盖 `& < > " '` 五个字符。

---

### 12.13 评测系统（`eval/run.py`）

#### 测试题结构

```json
{
    "id": "E001",
    "category": "结算",
    "risk": "high",
    "question": "蒙东电力交易中长期合约如何结算？结算周期是多久？",
    "must_contain": ["月", "结算"],
    "must_not": [],
    "expect_refuse": false,
    "notes": "基础结算规则，必须命中月度结算"
}
```

#### 判定逻辑

```python
def evaluate_one(vectorstore, q):
    result = rag_app.ask(vectorstore, question)
    
    refused = "未检索到足够依据" in answer
    
    if expect_refuse:            # 应拒答（如实时电价、电费计算）
        passed = refused
    elif missing_keywords:       # 必须包含的关键词缺失
        passed = False, status = "FAIL"
    elif forbidden_keywords:     # 禁止出现的关键词出现
        passed = False, status = "WARN"
    else:
        passed = True, status = "PASS"
```

#### 15 道测试题覆盖范围

| 分类 | 题数 | 风险分布 |
|---|---|---|
| 结算 | 3 | high×2, medium×1 |
| 注册 | 2 | high×1, medium×1 |
| 申报 | 2 | medium×2 |
| 价格 | 1 | high×1 |
| 电量 | 1 | medium×1 |
| 合同 | 1 | medium×1 |
| 规则否定 | 2 | high×2 |
| 表格 | 1 | medium×1 |
| 不可回答 | 2 | low×2 |

---

### 12.14 日志追踪（`rag_trace.jsonl`）

每次问答写入一行 JSON：

```json
{
    "ts": "2026-05-30T14:22:05",
    "question": "蒙东电力交易的中长期合约如何结算？",
    "answer": "一、结论\n...",
    "sources": [...],
    "model": "qwen2.5:7b",
    "embed_model": "nomic-embed-text",
    "vector_backend": "faiss",
    "retrieval_k": 10,
    "candidate_k": 120,
    "max_chunks_per_source": 5,
    "prompt_version": "rag_prompt_v4_qwen"
}
```

**使用场景**：
- 用 `grep` / `jq` 分析特定问题的召回效果
- 统计不同问题的平均来源数
- 收集低质量回答用于评测集扩充
- 对比不同参数配置下的回答质量

---

### 12.15 错误处理全景

```
文档加载:
  pdfplumber 失败 → 降级 pypdf
  python-docx 不可用 → 降级 docx2txt
  data/ 不存在或为空 → 打印 ERROR 并退出

索引加载:
  index.faiss/index.pkl 不存在 → 返回 None（触发自动构建）
  manifest 不存在 → 打印 WARN，继续使用旧索引
  manifest 字段不匹配 → 打印 WARN，提示可能过期

嵌入:
  Ollama 连接失败 → HTTP 异常向上传播

检索:
  similarity_search_with_score 不可用 → 回退到 similarity_search (无分数)

生成:
  requests.ConnectionError → "[ERROR] 无法连接 Ollama，请先运行: ollama serve"
  requests.Timeout → "[ERROR] 模型推理超时"
  requests.HTTPError → "[ERROR] Ollama HTTP 调用失败：{e}"

API 层:
  向量库未加载 → HTTP 503
  问题为空 → HTTP 422
  Ollama 不可用 → HTTP 503
  未知异常 → HTTP 500
```

---

## 十三、打包交付方案

> 本章为送交甲方测试前的打包交付提供完整方案，包括文件整理、一键启动脚本、环境说明和验收清单。

---

### 13.1 交付物清单

| # | 文件/目录 | 说明 | 必需 |
|---|---|---|---|
| 1 | `rag_app.py` | RAG 核心引擎 | ✅ |
| 2 | `api_app.py` | Web/API 服务入口 | ✅ |
| 3 | `masker.py` | 脱敏模块 | ✅ |
| 4 | `check_env.py` | 环境检查脚本 | ✅ |
| 5 | `requirements.txt` | Python 依赖清单 | ✅ |
| 6 | `web/index.html` | Web 前端页面 | ✅ |
| 7 | `eval/` | 评测系统 | ✅ |
| 8 | `README.md` | 完整技术文档 | ✅ |
| 9 | `USER_GUIDE.md` | 用户操作指南 | ✅ |
| 10 | `data/` | 知识源文档（PDF/DOCX） | ✅（核心价值） |
| 11 | `faiss_index/` | 预构建的向量索引 | ⚠️ 可选（甲方可自行构建） |
| 12 | `logs/` | 日志目录 | ❌（交付前清空） |
| 13 | `__pycache__/` | Python 缓存 | ❌（交付前清除） |
| 14 | 启动脚本 | 一键启动批处理 | ✅（提升体验） |

---

### 13.2 推荐方案：ZIP 归档 + 批处理启动脚本

这是最适合甲方 Windows 环境的方案，零额外依赖。

#### 步骤一：清理项目目录

```powershell
cd "D:\Project Repository\md_transaction"

# 删除 Python 缓存
Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# 清空日志
Remove-Item -Recurse -Force logs\* -ErrorAction SilentlyContinue

# 删除旧索引（让甲方首次运行时自动构建，或保留预构建索引）
# 选项A：删除，让甲方自行构建
Remove-Item -Recurse -Force faiss_index -ErrorAction SilentlyContinue
# 选项B：保留预构建索引（如果甲方电脑配置相同）

# 删除 .git 目录（不给甲方源码仓库历史）
Remove-Item -Recurse -Force .git -ErrorAction SilentlyContinue
```

#### 步骤二：创建启动脚本

创建 `启动服务.bat`（Windows 批处理）：

```batch
@echo off
chcp 65001 >nul
title MD Transaction RAG 问答服务

echo ============================================
echo   蒙东电力交易规则智能问答系统
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 检查 Ollama
ollama list >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Ollama，请先安装并拉取模型
    echo 下载地址: https://ollama.com/
    echo 安装后运行:
    echo   ollama pull qwen2.5:7b
    echo   ollama pull nomic-embed-text
    pause
    exit /b 1
)

:: 检查依赖
python -c "import fastapi" >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 正在安装 Python 依赖...
    python -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
)

:: 环境检查
echo [检查] 正在检查环境...
python check_env.py
echo.

:: 启动服务
echo [启动] 正在启动问答服务...
echo 浏览器将自动打开 http://127.0.0.1:8000/
echo 按 Ctrl+C 停止服务
echo ============================================
python api_app.py

pause
```

创建 `环境检查.bat`：

```batch
@echo off
chcp 65001 >nul
title 环境检查

echo ============================================
echo   环境检查
echo ============================================
python check_env.py
echo.
pause
```

#### 步骤三：编写交付说明

创建 `交付说明.md`：

```markdown
# 蒙东电力交易规则智能问答系统 — 交付说明

## 一、系统概述

本系统是一个本地化电力交易规则智能问答工具，将蒙东电力交易相关的
PDF/DOCX 规则文档构建为知识库，支持自然语言提问，自动检索依据并生
成带来源追溯的回答。

## 二、运行环境要求

| 组件 | 最低要求 | 说明 |
|---|---|---|
| 操作系统 | Windows 10/11 64位 | macOS/Linux 亦可，但未经充分验证 |
| Python | 3.10 或更高 | https://www.python.org/downloads/ |
| Ollama | 最新版 | https://ollama.com/ |
| 内存 | 16GB 或更高 | 模型需约 5GB，操作系统和索引需额外空间 |
| 磁盘 | 20GB 可用空间 | 模型文件约 5GB + 知识库和索引 |

## 三、首次使用步骤

### 1. 安装 Python 3.10+

从 https://www.python.org/downloads/ 下载安装。
安装时务必勾选 "Add Python to PATH"。

### 2. 安装 Ollama 并拉取模型

从 https://ollama.com/ 下载安装 Ollama。

安装完成后，打开 PowerShell 或命令提示符，运行：

```powershell
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

### 3. 解压交付包

将交付包解压到任意目录（建议不含中文和空格，如 `D:\md_rag\`）。

### 4. 双击启动

双击 `启动服务.bat`，首次运行会自动：
- 安装 Python 依赖
- 检查环境配置
- 从 data/ 目录构建知识库索引（需等待几分钟）
- 启动 Web 服务并自动打开浏览器

此后再次启动只需几秒。

### 5. 开始使用

浏览器自动打开 http://127.0.0.1:8000/ ，在输入框中输入问题，
按 Enter 提交。

## 四、知识库内容

当前知识库包含以下文档：

| 文件名 | 类型 | 说明 |
|---|---|---|
| (根据实际 data/ 目录列出) | | |

## 五、技术支持

如遇问题，请先运行 `环境检查.bat` 查看详细诊断信息。
常用问题排查见 USER_GUIDE.md。
```

#### 步骤四：打包

```powershell
cd "D:\Project Repository\md_transaction"

# 方案 A：使用 PowerShell 压缩
Compress-Archive -Path @(
    "rag_app.py",
    "api_app.py",
    "masker.py",
    "check_env.py",
    "requirements.txt",
    "README.md",
    "USER_GUIDE.md",
    "交付说明.md",
    "启动服务.bat",
    "环境检查.bat",
    "data",
    "eval",
    "web"
) -DestinationPath "..\md_transaction_交付包_v1.0.zip" -Force

# 方案 B：直接复制到一个干净目录
$dest = "..\md_transaction_交付_v1.0"
New-Item -ItemType Directory -Force $dest
Copy-Item -Recurse @(
    "rag_app.py", "api_app.py", "masker.py", "check_env.py",
    "requirements.txt", "README.md", "USER_GUIDE.md",
    "启动服务.bat", "环境检查.bat",
    "data", "eval", "web"
) $dest
```

---

### 13.3 备选方案：带预构建索引的交付

如果甲方的硬件和软件环境与你相同（Windows + 同版本 Ollama + 同版本模型），可以考虑预构建索引一并交付，节省首次构建时间。

**优点**：甲方解压后即可使用，首次无需等待索引构建

**缺点**：
- FAISS 索引的 `index.pkl` 使用 pickle 序列化，跨 Python 版本可能不兼容
- 索引文件体积较大（数百 MB 到 GB 级）
- 知识源文件仍须附带（用户可能需要查看原文）

**操作**：

```powershell
# 构建索引后不清除 faiss_index/
# 将 faiss_index/ 一并打包
```

并在 `启动服务.bat` 中跳过索引自动构建逻辑（或将 `faiss_index/` 标记为可选）。

---

### 13.4 备选方案：Docker 容器化交付

适用于甲方有 Docker 环境的场景。需编写 Dockerfile：

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*

# 安装 Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

# 复制项目文件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY rag_app.py api_app.py masker.py check_env.py ./
COPY web/ ./web/
COPY eval/ ./eval/
COPY data/ ./data/

# 启动脚本：拉模型 + 构建索引 + 启动服务
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
```

**Docker 方案的限制**：
- Ollama 在 Docker 内运行需要 GPU 直通或较大内存
- 模型文件每次启动都要重新下载（除非挂载 volume）
- 增加了甲方的技术门槛
- **当前不推荐作为主要交付方案**

---

### 13.5 备选方案：PyInstaller 打包为 EXE

理论上可以将 Python 脚本打包为独立 .exe，但 **不推荐**：

**原因**：
- FAISS 的 C++ 扩展打包复杂，`faiss-cpu` 依赖 `numpy`、`libopenblas` 等 native 库
- `pdfplumber` 依赖 `pdfminer.six`，打包后可能出现 Unicode 数据文件缺失
- 打包后的 .exe 体积巨大（>500MB），且每次代码改动都需重新打包
- 调试困难，日志输出不友好

**如果甲方坚持要 EXE**，可使用以下命令：

```powershell
pip install pyinstaller
pyinstaller --onefile --add-data "web;web" --add-data "data;data" api_app.py
```

并在代码中将 `Path(__file__).parent` 相关的路径改为 `sys._MEIPASS` 兼容逻辑。

---

### 13.6 验收测试建议

建议在交付前准备好以下验收用例，供甲方测试人员使用：

| # | 测试问题 | 预期结果 |
|---|---|---|
| 1 | "蒙东电力交易的中长期合约如何结算？" | 回答含结算方式和月度周期，标注 [S1][S2] |
| 2 | "市场主体注册需要什么条件？" | 回答含注册条件，有章节定位 |
| 3 | "什么是偏差电量？" | 回答含偏差定义，标注来源 |
| 4 | "明天蒙东的现货电价是多少？" | 应拒答："未检索到足够依据" |
| 5 | "请帮我算电费" | 应拒答 |
| 6 | 输入空白问题直接提交 | API 返回 422 |
| 7 | 运行 `python eval/run.py` | 通过率 ≥ 80%（13/15） |

---

### 13.7 交付前检查清单

- [ ] `__pycache__/` 已删除
- [ ] `.git/` 已删除（如不需要）
- [ ] `logs/` 已清空
- [ ] `data/` 中知识源文件完整且脱敏策略已确认
- [ ] `启动服务.bat` 已创建并测试
- [ ] `环境检查.bat` 已创建并测试
- [ ] `交付说明.md` 已填写（尤其是知识库文档列表和技术支持联系方式）
- [ ] `README.md` 已更新
- [ ] `requirements.txt` 版本号已锁定（建议改为 `==` 精确版本）
- [ ] 在干净环境（或另一台电脑）上完整走通一次"解压→启动→问答→日志检查"流程
- [ ] `python eval/run.py` 全部通过
- [ ] 确认 Ollama 模型名称与甲方环境一致（`qwen2.5:7b` 是否有特定 tag）

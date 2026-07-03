"""Docker 环境端到端验证 — 通过真实日志确认混合检索链路生效。

本测试通过 httpx 调用 Docker 化应用的 REST API，并通过 ``docker compose logs``
解析结构化 BIZ_EVENT 日志来验证检索链路正确性。

模式控制：
    通过 ``E2E_RETRIEVAL_MODE`` 环境变量控制当前测试轮次期望的检索模式。
    - ``hybrid``（默认）: 验证双路召回 + RRF 融合全链路。
    - ``vector``: 仅验证向量召回，断言 BM25 日志不出现。
    - ``bm25``: 仅验证关键词召回。

用法（配合 e2e_verify.sh）::

    E2E_RETRIEVAL_MODE=hybrid uv run pytest tests/e2e/test_docker_e2e_hybrid.py -v -s -m e2e
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest

# ── 覆盖 conftest autouse fixture ─────────────────────────────────────
# tests/e2e/conftest.py 的 _require_test_db 要求连接 test-db (5433)，
# 本测试直接操作 Docker 应用，不需要 test-db。


@pytest.fixture(autouse=True)
def _require_test_db():
    """覆盖 conftest autouse — Docker E2E 不需要 test-db。"""
    pass


# ── 配置 ──────────────────────────────────────────────────────────────
APP_URL = os.environ.get("E2E_APP_URL", "http://localhost:8000")
TEST_DATA_DIR = os.environ.get(
    "E2E_TEST_DATA_DIR",
    r"E:\study_data\AI\Hello Agents\hello-agents-main",
)
RETRIEVAL_MODE = os.environ.get("E2E_RETRIEVAL_MODE", "hybrid")
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent

# 至少上传的文档数
MIN_DOCS = 5

# 检索查询列表 — 每个模式至少执行一个查询
RETRIEVAL_QUERIES: dict[str, list[str]] = {
    "hybrid": [
        "什么是 RAG？如何构建检索增强生成系统？",
        "Agent 架构设计的最佳实践",
        "向量数据库的性能优化方法",
    ],
    "vector": [
        "大语言模型的训练方法",
    ],
    "bm25": [
        "知识图谱构建",
    ],
}

pytestmark = [pytest.mark.e2e]

# ── 工具函数 ──────────────────────────────────────────────────────────


def _docker_available() -> bool:
    """检查 Docker 是否可用。"""
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return True
    except Exception:
        return False


def _app_healthy(app_url: str = APP_URL, timeout: int = 30) -> bool:
    """轮询应用 /health 端点直到就绪或超时。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{app_url}/health", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _get_app_logs() -> str:
    """获取 Docker Compose app 服务的控制台日志（无颜色编码）。"""
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "logs",
                "app",
                "--no-color",
                "--no-log-prefix",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(PROJECT_DIR),
            check=False,
        )
        return result.stdout
    except Exception:
        return ""


def _parse_biz_events(logs: str) -> list[dict[str, str]]:
    """从日志文本解析所有 BIZ_EVENT 行，返回事件字典列表。

    日志格式::

        timestamp | level | module:func:lineno | event_type | extra_fields | message

    其中 ``extra_fields`` 为空格分隔的 ``key=value`` 字符串。
    value 可能包含引号包裹的空格（如 query 字段不用于精确解析，用 in 匹配即可）。
    """
    events: list[dict[str, str]] = []
    for line in logs.splitlines():
        if "| BIZ_EVENT |" not in line and "|BIZ_EVENT|" not in line:
            continue
        # 按管道分隔
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            continue
        # extra_fields 位于索引 4（0-indexed）
        extra_str = parts[4]
        event_data: dict[str, str] = {}
        # 解析 key=value 对 — 处理括号和引号内的空格
        pos = 0
        while pos < len(extra_str):
            eq = extra_str.find("=", pos)
            if eq == -1:
                break
            key_start = pos
            key = extra_str[key_start:eq]
            val_start = eq + 1
            val_end = val_start
            brace_depth = 0
            in_single_quote = False
            while val_end < len(extra_str):
                ch = extra_str[val_end]
                if in_single_quote:
                    if ch == "'":
                        in_single_quote = False
                elif ch == "'":
                    in_single_quote = True
                elif ch in ("[", "("):
                    brace_depth += 1
                elif ch in ("]", ")"):
                    brace_depth -= 1
                elif ch == " " and brace_depth == 0:
                    break
                val_end += 1
            value = extra_str[val_start:val_end]
            if key:  # 跳过空 key
                event_data[key] = value
            pos = val_end + 1
        events.append(event_data)
    return events


def _collect_md_files(data_dir: str) -> list[Path]:
    """递归收集目录下所有 .md 文件，按大小降序（取最大的先上传）。"""
    d = Path(data_dir)
    if not d.is_dir():
        return []
    files = list(d.rglob("*.md"))
    files.sort(key=lambda p: p.stat().st_size, reverse=True)
    return files


def _make_synthetic_docs(count: int = MIN_DOCS) -> list[tuple[str, bytes]]:
    """生成合成 Markdown 测试文档。用于测试数据目录不可用时。"""
    topics = [
        (
            "RAG 系统架构",
            (
                "检索增强生成 (Retrieval-Augmented Generation) 是一种将信息检索"
                "与生成模型相结合的 AI 架构。\n\n## 核心组件\n\nRAG 系统由三个"
                "核心组件构成：向量数据库、嵌入模型和生成模型。\n\n### 向量数据库"
                "\n存储文档的向量表示，支持高效的近似最近邻搜索。\n\n### 嵌入模型"
                "\n将文本转换为固定维度的向量表示。\n\n## 工作流程\n\n1. 用户提问"
                "\n2. 查询向量化\n3. 向量检索\n4. 上下文注入\n5. 生成回答\n"
            ),
        ),
        (
            "Agent 架构设计",
            (
                "AI Agent 是能够自主规划、执行和反思的智能体系统。\n\n## Agent 循环"
                "\n\n### 感知 (Perceive)\n从环境中获取信息。\n\n### 规划 (Plan)\n"
                "制定达成目标的步骤。\n\n### 执行 (Act)\n调用工具或 API 完成任务。"
                "\n\n### 反思 (Reflect)\n评估执行结果并调整策略。\n\n## 多 Agent 协作"
                "\n多个 Agent 可以通过消息传递进行协作，形成更强大的系统。\n"
            ),
        ),
        (
            "向量数据库对比",
            (
                "向量数据库是 AI 应用的关键基础设施。\n\n## 主流方案\n\n### Milvus"
                "\n开源向量数据库，支持十亿级向量检索。\n\n### Pinecone\n全托管向量"
                "数据库服务。\n\n### Weaviate\n支持混合检索的开源向量数据库。\n\n"
                "### Qdrant\nRust 实现的高性能向量数据库。\n\n## 选择标准\n- 性能需求"
                "（QPS / 延迟）\n- 数据规模\n- 部署方式（自托管 vs SaaS）\n"
            ),
        ),
        (
            "大语言模型训练",
            (
                "大型语言模型的训练是一个复杂的系统工程。\n\n## 预训练\n在海量文本"
                "语料上进行自监督学习。\n\n## 指令微调\n使用人工标注的指令数据对模型"
                "进行监督微调。\n\n## RLHF\n基于人类反馈的强化学习，使模型输出对齐"
                "人类偏好。\n\n## 评估方法\n- 困惑度 (Perplexity)\n- BLEU / ROUGE\n"
                "- 人工评估\n"
            ),
        ),
        (
            "知识图谱构建",
            (
                "知识图谱是结构化的知识表示方式。\n\n## 构建流程\n\n### 实体识别\n"
                "从非结构化文本中识别命名实体。\n\n### 关系抽取\n识别实体之间的语义"
                "关系。\n\n### 实体对齐\n将不同来源的实体进行匹配和合并。\n\n"
                "### 图谱存储\n使用图数据库（如 Neo4j）存储三元组。\n\n## 应用场景\n"
                "- 智能问答\n- 推荐系统\n- 风险控制\n"
            ),
        ),
        (
            "Python 异步编程",
            (
                "Python 的异步编程模型基于事件循环和协程。\n\n## asyncio 基础\n\n"
                "### 协程 (Coroutine)\n使用 async/await 语法定义的异步函数。\n\n"
                "### 事件循环 (Event Loop)\n管理和调度协程的执行。\n\n## 常见模式\n\n"
                "### 并发请求\n使用 asyncio.gather 并发执行多个异步操作。\n\n"
                "### 生产者-消费者\n使用 asyncio.Queue 实现异步任务调度。\n"
            ),
        ),
        (
            "Docker 容器化部署",
            (
                "Docker 是应用容器化的标准工具。\n\n## 核心概念\n\n### 镜像 (Image)"
                "\n包含应用及其依赖的只读模板。\n\n### 容器 (Container)\n镜像的运行"
                "实例，互相隔离。\n\n### Docker Compose\n多容器应用的定义和编排工具。"
                "\n\n## 最佳实践\n- 使用多阶段构建减小镜像体积\n- 合理使用 layer cache"
                "\n- 避免以 root 用户运行\n"
            ),
        ),
        (
            "Elasticsearch 全文检索",
            (
                "Elasticsearch 是一个分布式搜索和分析引擎。\n\n## 核心概念\n\n"
                "### 索引 (Index)\n文档的集合，类似关系数据库中的表。\n\n### 映射"
                " (Mapping)\n定义文档字段的类型和索引方式。\n\n### 分析器 (Analyzer)"
                "\n将文本转换为可搜索的词条。\n\n## BM25 算法\nOkapi BM25 是 "
                "Elasticsearch 的默认相关性评分算法，基于词频和逆文档频率。\n"
            ),
        ),
    ]

    docs: list[tuple[str, bytes]] = []
    for i, (title, body) in enumerate(topics[:count]):
        suffix = uuid.uuid4().hex[:8]
        content = (
            f"# {title} [{suffix}]\n\n{body}\n\n---\n"
            f"*测试文档 {i + 1}，唯一标识: {suffix}*\n"
        )
        docs.append((f"test_topic_{i + 1}_{suffix}.md", content.encode("utf-8")))
    return docs


# ── Module 级 Fixtures ───────────────────────────────────────────────


@pytest.fixture(scope="module")
def _require_docker_stack():
    """验证 Docker 栈（app + ES + PG）可用。不可用时给出明确修复指引。"""
    if not _docker_available():
        pytest.fail("Docker 不可用。请确保 Docker Desktop 已启动。")
    if not _app_healthy():
        # 尝试启动
        try:
            subprocess.run(
                ["docker", "compose", "up", "-d", "--wait"],
                timeout=120,
                cwd=str(PROJECT_DIR),
                check=True,
            )
            if not _app_healthy(timeout=60):
                pytest.fail("Docker 栈启动后应用仍未就绪（端口 8000）。")
        except Exception as exc:
            pytest.fail(
                f"Docker 栈启动失败: {exc}\n"
                f"请手动执行: cd {PROJECT_DIR} && docker compose up -d --wait"
            )


@pytest.fixture(scope="module")
def kb_id(_require_docker_stack) -> str:
    """创建测试知识库，返回 kb_id。module 级别 — 每个模式轮次仅创建一次。"""
    unique_name = f"E2E Hybrid Test {uuid.uuid4().hex[:8]}"
    try:
        resp = httpx.post(
            f"{APP_URL}/v1/knowledge-bases:create",
            json={"name": unique_name},
            timeout=15,
        )
        assert (
            resp.status_code == 200
        ), f"创建知识库失败: {resp.status_code} {resp.text}"
        return resp.json()["data"]["kb_id"]
    except httpx.ConnectError:
        pytest.fail(f"无法连接到 Docker 应用 ({APP_URL})，请检查服务是否运行。")


@pytest.fixture(scope="module")
def uploaded_docs(kb_id: str, _require_docker_stack) -> list[str]:
    """批量上传 Markdown 文档到知识库，返回 doc_id 列表。

    优先从 TEST_DATA_DIR 收集真实 MD 文件；目录不可用时使用合成数据。
    """
    doc_ids: list[str] = []

    # 收集 MD 文件
    md_files = _collect_md_files(TEST_DATA_DIR)
    if len(md_files) >= MIN_DOCS:
        # 取前 MIN_DOCS 个最大文件
        upload_files = md_files[:MIN_DOCS]
        for md_path in upload_files:
            content = md_path.read_bytes()
            suffix = uuid.uuid4().hex[:6]
            # 追加随机后缀使内容唯一（避免跨轮次 409）
            content = content + f"\n<!-- e2e:{suffix} -->\n".encode()
            filename = md_path.name
            doc_id = _upload_doc(kb_id, content, filename)
            if doc_id:
                doc_ids.append(doc_id)
    else:
        # 使用合成文档
        if md_files:
            print(
                f"  [WARNING] 测试数据目录仅有 {len(md_files)} 个 MD 文件，"
                f"需要至少 {MIN_DOCS}，使用合成文档作为补充。"
            )
        synthetic = _make_synthetic_docs(MIN_DOCS)
        for filename, content in synthetic:
            doc_id = _upload_doc(kb_id, content, filename)
            if doc_id:
                doc_ids.append(doc_id)

    assert (
        len(doc_ids) >= MIN_DOCS
    ), f"上传文档不足: 期望 >= {MIN_DOCS}，实际上传 {len(doc_ids)} 个。"
    return doc_ids


def _upload_doc(kb_id: str, content: bytes, filename: str) -> str | None:
    """上传单个文档，返回 doc_id。409（已存在）返回 None。"""
    try:
        resp = httpx.post(
            f"{APP_URL}/v1/documents:upload",
            data={"kb_id": kb_id},
            files={"file": (filename, content, "text/markdown")},
            timeout=60,
        )
        if resp.status_code == 409:
            return None  # 文档已存在，跳过
        assert (
            resp.status_code == 201
        ), f"上传文档 {filename} 失败: {resp.status_code} {resp.text}"
        return resp.json()["data"]["doc_id"]
    except httpx.ConnectError:
        pytest.fail(f"无法连接到 Docker 应用 ({APP_URL})。")


# ── 测试类 ────────────────────────────────────────────────────────────


class TestDockerHealth:
    """验证 Docker 栈健康状态。"""

    def test_app_health_ok(self, _require_docker_stack):
        """应用 /health 返回 ok。"""
        resp = httpx.get(f"{APP_URL}/health", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["checks"]["database"] == "ok"


class TestUploadLogEvents:
    """验证上传操作产生的日志事件。"""

    def test_keyword_upsert_done_logged(self, uploaded_docs):
        """上传成功后日志中包含 keyword_upsert_done 事件。"""
        logs = _get_app_logs()
        events = _parse_biz_events(logs)
        upsert_events = [e for e in events if e.get("event") == "keyword_upsert_done"]
        assert len(upsert_events) >= 1, (
            f"未找到 keyword_upsert_done 事件。"
            f"共解析 {len(events)} 个 BIZ_EVENT: "
            f"{[e.get('event') for e in events]}"
        )

    def test_document_uploaded_logged(self, uploaded_docs):
        """每次上传成功后日志中包含 document_uploaded 事件。"""
        logs = _get_app_logs()
        events = _parse_biz_events(logs)
        upload_events = [e for e in events if e.get("event") == "document_uploaded"]
        assert len(upload_events) >= MIN_DOCS, (
            f"期望 >= {MIN_DOCS} 个 document_uploaded 事件，"
            f"实际 {len(upload_events)} 个。"
        )


class TestRetrieveLogEvents:
    """验证检索操作产生的日志事件（核心验证）。"""

    @pytest.fixture(scope="class")
    def retrieve_result(self, kb_id, uploaded_docs):
        """执行一次检索，供后续测试复用。"""
        queries = RETRIEVAL_QUERIES.get(RETRIEVAL_MODE, RETRIEVAL_QUERIES["hybrid"])
        query = queries[0]
        try:
            resp = httpx.post(
                f"{APP_URL}/v1/rag:retrieve",
                json={
                    "query": query,
                    "kb_ids": [kb_id],
                    "top_k": 5,
                },
                timeout=30,
            )
            return {
                "query": query,
                "status_code": resp.status_code,
                "body": resp.json(),
            }
        except httpx.ConnectError:
            pytest.fail(f"无法连接到 Docker 应用 ({APP_URL})。")

    def test_retrieve_returns_200(self, retrieve_result):
        """检索请求返回 200。"""
        assert (
            retrieve_result["status_code"] == 200
        ), f"检索失败: {retrieve_result['status_code']}"

    def test_retrieve_returns_hits(self, retrieve_result):
        """检索返回至少一个结果。"""
        body = retrieve_result["body"]
        assert body["code"] == 0, f"检索错误: {body}"
        hits = body.get("data", {}).get("hits", [])
        assert len(hits) >= 1, f"检索未返回结果: {body}"

    def test_retrieve_completed_event_exists(self, retrieve_result):
        """检索完成后日志中包含 retrieve_completed 事件。"""
        logs = _get_app_logs()
        events = _parse_biz_events(logs)
        completed = [e for e in events if e.get("event") == "retrieve_completed"]
        assert len(completed) >= 1, (
            f"未找到 retrieve_completed 事件。"
            f"共 {len(events)} 个 BIZ_EVENT: "
            f"{[e.get('event') for e in events]}"
        )

    def test_retrieval_mode_in_log(self, retrieve_result):
        """retrieve_completed 事件包含正确的 retrieval_mode 字段。"""
        logs = _get_app_logs()
        events = _parse_biz_events(logs)
        completed = [e for e in events if e.get("event") == "retrieve_completed"]
        assert len(completed) >= 1, "未找到 retrieve_completed 事件"
        for evt in completed:
            mode = evt.get("retrieval_mode", "")
            assert (
                mode == RETRIEVAL_MODE
            ), f"retrieval_mode 不匹配: 期望 '{RETRIEVAL_MODE}'，实际 '{mode}'"


class TestKeywordSearchLogEvents:
    """验证关键词检索 (BM25) 相关日志事件。"""

    def test_keyword_search_done_in_hybrid_or_bm25(self, kb_id, uploaded_docs):
        """hybrid / bm25 模式下日志必须包含 keyword_search_done 事件。"""
        if RETRIEVAL_MODE not in ("hybrid", "bm25"):
            pytest.skip(f"当前模式 {RETRIEVAL_MODE} 不触发 BM25 检索")

        # 执行一次检索
        queries = RETRIEVAL_QUERIES.get(RETRIEVAL_MODE, [])
        if not queries:
            queries = ["RAG 架构"]
        with contextlib.suppress(Exception):
            httpx.post(
                f"{APP_URL}/v1/rag:retrieve",
                json={"query": queries[0], "kb_ids": [kb_id], "top_k": 5},
                timeout=30,
            )

        logs = _get_app_logs()
        events = _parse_biz_events(logs)
        keyword_events = [
            e
            for e in events
            if e.get("event") in ("keyword_search_done", "keyword_search_fail")
        ]

        assert len(keyword_events) >= 1, (
            "hybrid/bm25 模式下未找到 keyword_search_done 或 keyword_search_fail 事件。"
            f"共 {len(events)} 个 BIZ_EVENT"
        )

        # keyword_search_done 不应是 keyword_search_fail
        done = [e for e in keyword_events if e.get("event") == "keyword_search_done"]
        if not done:
            fail_events = [
                e for e in keyword_events if e.get("event") == "keyword_search_fail"
            ]
            pytest.fail(
                f"BM25 检索均失败: {len(fail_events)} 个 keyword_search_fail 事件"
            )

    def test_no_keyword_search_in_vector_mode(self, kb_id, uploaded_docs):
        """vector-only 模式下不应产生 keyword_search_done 事件。"""
        if RETRIEVAL_MODE != "vector":
            pytest.skip(f"当前模式 {RETRIEVAL_MODE}，仅 vector 模式验证此断言")

        # 执行检索
        with contextlib.suppress(Exception):
            httpx.post(
                f"{APP_URL}/v1/rag:retrieve",
                json={"query": "RAG 系统", "kb_ids": [kb_id], "top_k": 5},
                timeout=30,
            )

        logs = _get_app_logs()
        events = _parse_biz_events(logs)
        keyword_events = [
            e
            for e in events
            if e.get("event") in ("keyword_search_done", "keyword_search_fail")
        ]
        assert len(keyword_events) == 0, (
            f"vector 模式下不应产生关键词检索事件，" f"但发现 {len(keyword_events)} 个"
        )


class TestRRFFusion:
    """验证 RRF 融合相关日志字段（仅 hybrid 模式）。"""

    def test_rrf_pool_size_positive(self, kb_id, uploaded_docs):
        """hybrid 模式下 rrf_pool_size > 0，表示 RRF 融合后确实有去重结果。"""
        if RETRIEVAL_MODE != "hybrid":
            pytest.skip(f"当前模式 {RETRIEVAL_MODE}，仅 hybrid 模式验证 RRF")

        # 执行检索
        with contextlib.suppress(Exception):
            httpx.post(
                f"{APP_URL}/v1/rag:retrieve",
                json={
                    "query": "RAG 检索增强生成架构设计",
                    "kb_ids": [kb_id],
                    "top_k": 10,
                },
                timeout=30,
            )

        logs = _get_app_logs()
        events = _parse_biz_events(logs)
        completed = [e for e in events if e.get("event") == "retrieve_completed"]

        rrf_values: list[int] = []
        for evt in completed:
            if evt.get("retrieval_mode") == "hybrid":
                with contextlib.suppress(ValueError, TypeError):
                    rrf_values.append(int(evt.get("rrf_pool_size", "0")))

        assert (
            rrf_values
        ), "未找到 hybrid 模式的 retrieve_completed 事件（含 rrf_pool_size）"
        assert all(
            v > 0 for v in rrf_values
        ), f"rrf_pool_size 应 > 0: 实际值 {rrf_values}"

    def test_keyword_hit_count_positive(self, kb_id, uploaded_docs):
        """hybrid 模式下 keyword_hit_count > 0，确认 BM25 确实召回了结果。"""
        if RETRIEVAL_MODE != "hybrid":
            pytest.skip(f"当前模式 {RETRIEVAL_MODE}，仅 hybrid 模式验证")

        logs = _get_app_logs()
        events = _parse_biz_events(logs)
        completed = [e for e in events if e.get("event") == "retrieve_completed"]

        kw_counts: list[int] = []
        for evt in completed:
            if evt.get("retrieval_mode") == "hybrid":
                with contextlib.suppress(ValueError, TypeError):
                    kw_counts.append(int(evt.get("keyword_hit_count", "0")))

        assert kw_counts, "未找到 hybrid 模式的检索事件（含 keyword_hit_count）"
        assert all(
            c > 0 for c in kw_counts
        ), f"keyword_hit_count 应 > 0（BM25 需实际召回结果）: 实际值 {kw_counts}"


class TestModeComparison:
    """跨模式对比：确认不同模式的检索结果有可观测差异。"""

    def test_results_recorded_per_mode(self, kb_id, uploaded_docs):
        """记录各模式检索结果，供 e2e_verify.sh 汇总对比。"""
        queries = RETRIEVAL_QUERIES.get(RETRIEVAL_MODE, ["RAG"])
        query = queries[0]
        try:
            resp = httpx.post(
                f"{APP_URL}/v1/rag:retrieve",
                json={"query": query, "kb_ids": [kb_id], "top_k": 5},
                timeout=30,
            )
            assert resp.status_code == 200
            body = resp.json()
            hits = body.get("data", {}).get("hits", [])
            print(
                f"\nMODE_RESULT | mode={RETRIEVAL_MODE} "
                f"query={query} hit_count={len(hits)}"
            )
            assert len(hits) >= 1, f"{RETRIEVAL_MODE} 模式返回空结果"
        except httpx.ConnectError:
            pytest.fail(f"无法连接到 Docker 应用 ({APP_URL})。")

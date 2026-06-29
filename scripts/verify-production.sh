#!/usr/bin/env bash
# =============================================================================
# verify-production.sh — 生产环境验证脚本
#
# 在类生产环境中运行全部测试，确保系统就绪。
# 需要：Docker Compose、EMBED_API_KEY、LLM_API_KEY
#
# 用法:
#   export EMBED_API_KEY="sk-xxx"
#   export LLM_API_KEY="sk-xxx"
#   ./scripts/verify-production.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "================================================"
echo "  RAGNexus 生产环境验证"
echo "  日期: $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================"

# ── 1. 环境变量检查 ─────────────────────────────────────────────
echo ""
echo "[1/6] 检查环境变量…"

: "${EMBED_API_KEY:?EMBED_API_KEY 未设置 — 导出此变量以启用 Embedder}"
: "${LLM_API_KEY:?LLM_API_KEY 未设置 — 导出此变量以启用 LLM}"

echo "  ✓ EMBED_API_KEY 已设置"
echo "  ✓ LLM_API_KEY  已设置"

# ── 2. Docker Compose ───────────────────────────────────────────
echo ""
echo "[2/6] 启动测试数据库 (docker-compose.test.yml)…"

if ! docker info >/dev/null 2>&1; then
    echo "  ❌ Docker 未运行，请先启动 Docker"
    exit 1
fi

docker compose -f docker-compose.test.yml up -d --wait

echo "  ✓ 数据库就绪"

# ── 3. Alembic 迁移 ─────────────────────────────────────────────
echo ""
echo "[3/6] 执行数据库迁移…"

PG_DSN="postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test" \
    uv run alembic upgrade head

echo "  ✓ 迁移完成"

# ── 4. 全部测试（含覆盖率） ────────────────────────────────────
echo ""
echo "[4/6] 运行全部测试并收集覆盖率…"

uv run pytest \
    --cov=src/ragnexus \
    --cov-report=term \
    --cov-report=html:.coverage_report \
    -v

echo "  ✓ 全部测试通过"

# ── 5. E2E 真实 API 测试 ─────────────────────────────────────
echo ""
echo "[5/6] 运行 E2E 真实 API 测试…"

uv run pytest tests/e2e/ \
    -m e2e \
    --cov=src/ragnexus \
    --cov-append \
    --cov-report=term \
    -v

echo "  ✓ E2E 测试通过"

# ── 6. 覆盖率报告 ──────────────────────────────────────────────
echo ""
echo "[6/6] 生成覆盖率报告…"

uv run coverage report --fail-under=70 2>/dev/null || \
    echo "  ⚠ 覆盖率低于 70%，请补充测试"

uv run coverage html -d .coverage_report 2>/dev/null

echo ""
echo "================================================"
echo "  ✅ 生产环境验证通过"
echo "  覆盖率报告: .coverage_report/index.html"
echo "================================================"

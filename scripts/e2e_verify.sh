#!/usr/bin/env bash
# =============================================================================
# e2e_verify.sh — RAGNexus 混合检索 E2E 验证
#
# 分三轮运行 Docker 栈，分别以 hybrid / vector / bm25 三种检索模式
# 运行 E2E 测试，验证每轮模式的日志事件和检索结果。
#
# 用法:
#   chmod +x scripts/e2e_verify.sh
#   ./scripts/e2e_verify.sh
#
# 依赖: Docker Compose, uv, curl
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

COMPOSE_FILE="docker-compose.yml"
COMPOSE_BACKUP="${COMPOSE_FILE}.e2e-backup"
TEST_FILE="tests/e2e/test_docker_e2e_hybrid.py"
APP_URL="${E2E_APP_URL:-http://localhost:8000}"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 结果统计
PASS_COUNT=0
FAIL_COUNT=0
declare -A MODE_HIT_COUNTS

echo ""
echo -e "${CYAN}================================================${NC}"
echo -e "${CYAN}  RAGNexus 混合检索 E2E 验证${NC}"
echo -e "${CYAN}  日期: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo -e "${CYAN}================================================${NC}"

# ── 0. 前置检查 ───────────────────────────────────────────────────

echo ""
echo -e "${YELLOW}[0/4] 前置检查…${NC}"

if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}[FAIL] Docker 不可用。请启动 Docker Desktop。${NC}"
    exit 1
fi
echo "  Docker: OK"

if ! command -v uv &>/dev/null; then
    echo -e "${RED}[FAIL] uv 未安装。请执行: pip install uv${NC}"
    exit 1
fi
echo "  uv: OK"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo -e "${RED}[FAIL] 未找到 $COMPOSE_FILE${NC}"
    exit 1
fi
echo "  docker-compose.yml: OK"

# 备份原始 compose 文件
cp "$COMPOSE_FILE" "$COMPOSE_BACKUP"
trap 'echo ""; echo -e "${YELLOW}恢复原始 docker-compose.yml…${NC}"; mv "$COMPOSE_BACKUP" "$COMPOSE_FILE"' EXIT

# ── 1. 构建镜像（仅一次） ─────────────────────────────────────────

echo ""
echo -e "${YELLOW}[1/4] 构建 Docker 镜像…${NC}"
docker compose build --quiet app 2>&1 | tail -5
echo -e "${GREEN}  构建完成${NC}"

# ── 2. 三轮模式验证 ───────────────────────────────────────────────

MODES=("hybrid" "vector" "bm25")

for MODE in "${MODES[@]}"; do
    echo ""
    echo -e "${CYAN}------------------------------------------------${NC}"
    echo -e "${CYAN}  [2/4] 模式: ${MODE}${NC}"
    echo -e "${CYAN}------------------------------------------------${NC}"

    # 停止旧服务
    echo "  停止旧服务…"
    docker compose down --timeout 10 2>/dev/null || true

    # 修改 RETRIEVAL_MODE（兼容 Linux 和 macOS 的 sed）
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/RETRIEVAL_MODE: .*/RETRIEVAL_MODE: ${MODE}/" "$COMPOSE_FILE"
    else
        sed -i "s/RETRIEVAL_MODE: .*/RETRIEVAL_MODE: ${MODE}/" "$COMPOSE_FILE"
    fi
    echo "  RETRIEVAL_MODE 已设置为: ${MODE}"

    # 启动服务
    echo "  启动服务 (docker compose up -d --wait)…"
    if ! docker compose up -d --wait 2>&1 | tail -10; then
        echo -e "${RED}[FAIL] 服务启动失败${NC}"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        continue
    fi

    # 等待应用真正就绪
    echo "  等待应用 /health…"
    for i in $(seq 1 30); do
        if curl -s "${APP_URL}/health" | grep -q '"status":"ok"'; then
            echo -e "  ${GREEN}应用就绪${NC}"
            break
        fi
        if [ "$i" -eq 30 ]; then
            echo -e "${RED}[FAIL] 应用 /health 超时${NC}"
            FAIL_COUNT=$((FAIL_COUNT + 1))
            continue 2  # 跳到下一个模式
        fi
        sleep 2
    done

    # 运行测试
    echo ""
    echo "  运行 E2E 测试 (mode=${MODE})…"
    if E2E_RETRIEVAL_MODE="${MODE}" uv run pytest "$TEST_FILE" -v -s -m e2e \
        --tb=short 2>&1; then
        echo -e "  ${GREEN}[PASS] ${MODE} 模式测试通过${NC}"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo -e "${RED}[FAIL] ${MODE} 模式测试失败${NC}"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi

    # ── 2a. 日志验证 ──────────────────────────────────────────
    echo ""
    echo "  --- 日志事件检查 ---"

    echo "  [keyword_search_done]:"
    docker compose logs app --no-color 2>/dev/null \
        | grep -c "event=keyword_search_done" \
        || echo "    0 条"

    echo "  [retrieve_completed]:"
    docker compose logs app --no-color 2>/dev/null \
        | grep -c "event=retrieve_completed" \
        || echo "    0 条"

    echo "  [retrieve_completed 含 retrieval_mode]:"
    docker compose logs app --no-color 2>/dev/null \
        | grep "event=retrieve_completed" \
        | grep -o "retrieval_mode=[^ ]*" \
        || echo "    (无)"

    echo "  [rrf_pool_size > 0]:"
    docker compose logs app --no-color 2>/dev/null \
        | grep "event=retrieve_completed" \
        | grep -o "rrf_pool_size=[0-9]*" \
        || echo "    (无)"

    echo "  [keyword_hit_count > 0]:"
    docker compose logs app --no-color 2>/dev/null \
        | grep "event=retrieve_completed" \
        | grep -o "keyword_hit_count=[0-9]*" \
        || echo "    (无)"

    echo "  [keyword_upsert_done]:"
    docker compose logs app --no-color 2>/dev/null \
        | grep -c "event=keyword_upsert_done" \
        || echo "    0 条"
done

# ── 3. 清理 ───────────────────────────────────────────────────────

echo ""
echo -e "${YELLOW}[3/4] 停止服务…${NC}"
docker compose down --timeout 10 2>/dev/null || true

# ── 4. 汇总 ───────────────────────────────────────────────────────

echo ""
echo -e "${CYAN}================================================${NC}"
echo -e "${CYAN}  验证结果汇总${NC}"
echo -e "${CYAN}================================================${NC}"

TOTAL=$((PASS_COUNT + FAIL_COUNT))
echo -e "  通过: ${GREEN}${PASS_COUNT}${NC} / ${TOTAL}"
echo -e "  失败: ${RED}${FAIL_COUNT}${NC} / ${TOTAL}"

echo ""
echo "详细日志:"
for MODE in "${MODES[@]}"; do
    echo "  docker compose logs app | grep -E 'BIZ_EVENT.*${MODE}'"
done

if [ "$FAIL_COUNT" -eq 0 ]; then
    echo ""
    echo -e "${GREEN}  ✅ 全部模式验证通过！${NC}"
    exit 0
else
    echo ""
    echo -e "${RED}  ❌ 存在失败模式，请检查日志。${NC}"
    exit 1
fi

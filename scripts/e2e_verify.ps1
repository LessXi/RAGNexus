# =============================================================================
# e2e_verify.ps1 — RAGNexus 混合检索 E2E 验证 (Windows PowerShell)
#
# 分三轮运行 Docker 栈，分别以 hybrid / vector / bm25 三种检索模式
# 运行 E2E 测试，验证每轮模式的日志事件和检索结果。
#
# 用法:
#   .\scripts\e2e_verify.ps1
#
# 依赖: Docker Compose, uv
# =============================================================================

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
Set-Location $ProjectDir

$ComposeFile = "docker-compose.yml"
$ComposeBackup = "$ComposeFile.e2e-backup"
$TestFile = "tests/e2e/test_docker_e2e_hybrid.py"
$AppUrl = if ($env:E2E_APP_URL) { $env:E2E_APP_URL } else { "http://localhost:8000" }

$PassCount = 0
$FailCount = 0

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  RAGNexus 混合检索 E2E 验证 (PowerShell)" -ForegroundColor Cyan
Write-Host "  日期: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# ── 0. 前置检查 ───────────────────────────────────────────────────

Write-Host ""
Write-Host "[0/4] 前置检查..." -ForegroundColor Yellow

try {
    $null = docker info 2>&1
    Write-Host "  Docker: OK"
}
catch {
    Write-Host "[FAIL] Docker 不可用。请启动 Docker Desktop。" -ForegroundColor Red
    exit 1
}

try {
    $null = uv --version 2>&1
    Write-Host "  uv: OK"
}
catch {
    Write-Host "[FAIL] uv 未安装。请执行: pip install uv" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $ComposeFile)) {
    Write-Host "[FAIL] 未找到 $ComposeFile" -ForegroundColor Red
    exit 1
}
Write-Host "  docker-compose.yml: OK"

# 备份原始 compose 文件
Copy-Item $ComposeFile $ComposeBackup -Force

# ── 1. 构建镜像（仅一次） ─────────────────────────────────────────

Write-Host ""
Write-Host "[1/4] 构建 Docker 镜像..." -ForegroundColor Yellow
docker compose build --quiet app 2>&1 | Select-Object -Last 5
Write-Host "  构建完成" -ForegroundColor Green

# ── 2. 三轮模式验证 ───────────────────────────────────────────────

$Modes = @("hybrid", "vector", "bm25")

foreach ($Mode in $Modes) {
    Write-Host ""
    Write-Host "------------------------------------------------" -ForegroundColor Cyan
    Write-Host "  [2/4] 模式: $Mode" -ForegroundColor Cyan
    Write-Host "------------------------------------------------" -ForegroundColor Cyan

    # 停止旧服务
    Write-Host "  停止旧服务..."
    docker compose down --timeout 10 2>$null

    # 修改 RETRIEVAL_MODE
    $composeContent = Get-Content $ComposeFile -Raw
    $composeContent = $composeContent -replace 'RETRIEVAL_MODE: .*', "RETRIEVAL_MODE: $Mode"
    Set-Content $ComposeFile $composeContent -NoNewline
    Write-Host "  RETRIEVAL_MODE 已设置为: $Mode"

    # 启动服务
    Write-Host "  启动服务 (docker compose up -d --wait)..."
    try {
        docker compose up -d --wait 2>&1 | Select-Object -Last 10
    }
    catch {
        Write-Host "[FAIL] 服务启动失败: $_" -ForegroundColor Red
        $FailCount++
        continue
    }

    # 等待应用真正就绪
    Write-Host "  等待应用 /health..."
    $ready = $false
    for ($i = 1; $i -le 30; $i++) {
        try {
            $resp = Invoke-RestMethod -Uri "$AppUrl/health" -TimeoutSec 3 -ErrorAction Stop
            if ($resp.status -eq "ok") {
                Write-Host "  应用就绪" -ForegroundColor Green
                $ready = $true
                break
            }
        }
        catch {}
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        Write-Host "[FAIL] 应用 /health 超时" -ForegroundColor Red
        $FailCount++
        continue
    }

    # 运行测试
    Write-Host ""
    Write-Host "  运行 E2E 测试 (mode=$Mode)..."
    $env:E2E_RETRIEVAL_MODE = $Mode
    try {
        uv run pytest $TestFile -v -s -m e2e --tb=short 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [PASS] $Mode 模式测试通过" -ForegroundColor Green
            $PassCount++
        }
        else {
            Write-Host "  [FAIL] $Mode 模式测试失败" -ForegroundColor Red
            $FailCount++
        }
    }
    catch {
        Write-Host "  [FAIL] $Mode 模式测试异常: $_" -ForegroundColor Red
        $FailCount++
    }

    # ── 2a. 日志验证 ──────────────────────────────────────────
    Write-Host ""
    Write-Host "  --- 日志事件检查 ---"

    $logs = docker compose logs app --no-color 2>$null

    Write-Host "  [keyword_search_done]:"
    ($logs | Select-String "event=keyword_search_done").Count

    Write-Host "  [retrieve_completed]:"
    ($logs | Select-String "event=retrieve_completed").Count

    Write-Host "  [retrieve_completed 含 retrieval_mode]:"
    $logs | Select-String "event=retrieve_completed" | ForEach-Object {
        if ($_ -match "retrieval_mode=(\S+)") { $matches[1] }
    }

    Write-Host "  [rrf_pool_size > 0]:"
    $logs | Select-String "event=retrieve_completed" | ForEach-Object {
        if ($_ -match "rrf_pool_size=(\d+)") { $matches[1] }
    }

    Write-Host "  [keyword_hit_count > 0]:"
    $logs | Select-String "event=retrieve_completed" | ForEach-Object {
        if ($_ -match "keyword_hit_count=(\d+)") { $matches[1] }
    }

    Write-Host "  [keyword_upsert_done]:"
    ($logs | Select-String "event=keyword_upsert_done").Count
}

# ── 3. 清理 ───────────────────────────────────────────────────────

Write-Host ""
Write-Host "[3/4] 停止服务..." -ForegroundColor Yellow
docker compose down --timeout 10 2>$null

# 恢复 compose 文件
Copy-Item $ComposeBackup $ComposeFile -Force
Remove-Item $ComposeBackup -Force

# ── 4. 汇总 ───────────────────────────────────────────────────────

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  验证结果汇总" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

$Total = $PassCount + $FailCount
Write-Host "  通过: $PassCount / $Total" -ForegroundColor Green
Write-Host "  失败: $FailCount / $Total" -ForegroundColor Red

Write-Host ""
Write-Host "详细日志:"
foreach ($Mode in $Modes) {
    Write-Host "  docker compose logs app | Select-String 'BIZ_EVENT.*$Mode'"
}

if ($FailCount -eq 0) {
    Write-Host ""
    Write-Host "  ✓ 全部模式验证通过！" -ForegroundColor Green
    exit 0
}
else {
    Write-Host ""
    Write-Host "  ✗ 存在失败模式，请检查日志。" -ForegroundColor Red
    exit 1
}

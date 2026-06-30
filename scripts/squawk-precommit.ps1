# squawk pre-commit wrapper for Alembic .py migrations
# 策略：提取 op.execute("...") 中的裸 SQL，只扫 SQL 部分
# Python DSL 跳过，避免误报。报告模式 — 有问题显示但不阻塞提交

$squawk = "C:\Users\hj\squawk.exe"
$migrationsDir = "alembic\versions"
$tempSql = [System.IO.Path]::GetTempFileName() + ".sql"

try {
    $files = @(Get-ChildItem -Path $migrationsDir -Filter "*.py" -ErrorAction SilentlyContinue)
    if ($files.Count -eq 0) { exit 0 }

    $sqlStatements = @()
    foreach ($f in $files) {
        $content = Get-Content $f.FullName -Raw
        $matches = [regex]::Matches($content, "op\.execute\(\s*[""'](.+?)[""']\s*\)", "Singleline")
        foreach ($m in $matches) {
            $sqlStatements += $m.Groups[1].Value
        }
    }

    if ($sqlStatements.Count -eq 0) { exit 0 }

    $sqlStatements -join ";`n" | Out-File -FilePath $tempSql -Encoding ascii

    Write-Host "squawk: $($sqlStatements.Count) raw SQL statement(s) in migrations"

    $output = & $squawk $tempSql 2>&1
    if ($output) {
        $output | ForEach-Object { Write-Host $_ }
    }

    # 报告模式：始终 exit 0，不阻塞提交
    exit 0
}
finally {
    if (Test-Path $tempSql) { Remove-Item $tempSql -Force }
}

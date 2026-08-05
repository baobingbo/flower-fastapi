<#
.SYNOPSIS
    FlowerUI 开发环境一键重启脚本
.DESCRIPTION
    停止已运行的后端(5555)和前端(5556)服务，然后重新启动它们。
    后端使用 uvicorn，前端使用 Vite 开发服务器。
    适合开发过程中需要重启服务的场景。
.PARAMETER Mock
    是否启用模拟模式（FLOWER_MOCK=true），用于没有 Celery broker 时快速测试。
.PARAMETER Clean
    是否清理后端日志文件（_uvicorn_*.log、_server_stdout.log）。
.EXAMPLE
    .\dev-restart.ps1
    .\dev-restart.ps1 -Mock
    .\dev-restart.ps1 -Clean
#>

[CmdletBinding()]
param(
    [switch]$Mock,
    [switch]$Clean
)

# 设置 UTF-8 编码，避免中文乱码
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# ---------- 路径配置 ----------
$ROOT        = "$PSScriptRoot"
$BACKEND_DIR = Join-Path $ROOT "backend"
$FRONTEND_DIR= Join-Path $ROOT "frontend"
$VENV_DIR    = Join-Path $ROOT ".venv"
$PYTHON_EXE  = Join-Path $VENV_DIR "Scripts\python.exe"
$NODE_EXE    = Get-Command node -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source

# 服务端口
$BACKEND_PORT = 5555
$FRONTEND_PORT = 5556

# ---------- 颜色输出辅助函数 ----------
function Write-Info  { param($Msg) Write-Host "[INFO]  $Msg"  -ForegroundColor Cyan }
function Write-Success { param($Msg) Write-Host "[OK]    $Msg" -ForegroundColor Green }
function Write-Warn   { param($Msg) Write-Host "[WARN]  $Msg" -ForegroundColor Yellow }
function Write-Error  { param($Msg) Write-Host "[ERROR] $Msg" -ForegroundColor Red }

# ---------- 1. 停止已运行的服务 ----------
Write-Info "========== 第一步：停止已运行的服务 =========="

# 查找并终止占用后端端口的进程
$BackendPid = @(Get-NetTCPConnection -LocalPort $BACKEND_PORT -ErrorAction SilentlyContinue).OwningProcess
if ($BackendPid) {
    foreach ($pid in $BackendPid) {
        Write-Info "正在停止后端进程 (PID=$pid)..."
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
    Write-Success "后端服务已停止"
} else {
    Write-Info "后端服务未运行"
}

# 查找并终止占用前端端口的进程
$FrontendPids = @(Get-NetTCPConnection -LocalPort $FRONTEND_PORT -ErrorAction SilentlyContinue).OwningProcess
if ($FrontendPids) {
    foreach ($pid in $FrontendPids) {
        Write-Info "正在停止前端进程 (PID=$pid)..."
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
    Write-Success "前端服务已停止"
} else {
    Write-Info "前端服务未运行"
}

# ---------- 2. 清理日志（可选） ----------
if ($Clean) {
    Write-Info "清理后端日志文件..."
    Get-ChildItem -Path $BACKEND_DIR -Filter "_*.log" -ErrorAction SilentlyContinue | Remove-Item -Force
    Write-Success "日志已清理"
}

# ---------- 3. 检查依赖 ----------
Write-Info "========== 第二步：检查环境依赖 =========="

# 检查 Python 虚拟环境
if (-not (Test-Path $PYTHON_EXE)) {
    Write-Error "虚拟环境不存在: $PYTHON_EXE"
    Write-Info "请先运行: python -m venv .venv && .venv\Scripts\pip install -r backend\requirements.txt"
    exit 1
}
Write-Success "Python 虚拟环境: $PYTHON_EXE"

# 检查 Node.js
if (-not $NODE_EXE) {
    Write-Error "未找到 node，请先安装 Node.js"
    exit 1
}
Write-Success "Node.js: $NODE_EXE"

# 检查前端 node_modules
$FrontendNodeModules = Join-Path $FRONTEND_DIR "node_modules"
if (-not (Test-Path $FrontendNodeModules)) {
    Write-Warn "前端 node_modules 不存在，正在安装依赖..."
    Push-Location $FRONTEND_DIR
    npm install --registry=https://registry.npmmirror.com --no-audit --no-fund
    Pop-Location
    Write-Success "前端依赖安装完成"
} else {
    Write-Success "前端依赖已就绪"
}

# 检查后端 requirements
$BackendRequirements = Join-Path $BACKEND_DIR "requirements.txt"
if (-not (Test-Path $BackendRequirements)) {
    Write-Error "未找到 requirements.txt"
    exit 1
}
Write-Success "后端 requirements.txt 已找到"

# ---------- 4. 启动后端服务 ----------
Write-Info "========== 第三步：启动后端服务 =========="

$Env:FLOWER_MOCK = if ($Mock) { "true" } else { $null }
$Env:PYTHONIOENCODING = "utf-8"

# 使用 Start-Process 在后台启动后端，不阻塞脚本
$BackendProcess = Start-Process -FilePath $PYTHON_EXE `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", $BACKEND_PORT, "--reload" `
    -WorkingDirectory $BACKEND_DIR `
    -RedirectStandardOutput (Join-Path $BACKEND_DIR "_uvicorn_$(Get-Date -Format 'yyyyMMdd_HHmmss').log") `
    -RedirectStandardError (Join-Path $BACKEND_DIR "_uvicorn_err_$(Get-Date -Format 'yyyyMMdd_HHmmss').log") `
    -PassThru `
    -WindowStyle Normal

Write-Info "后端启动中 (PID=$($BackendProcess.Id))，端口 $BACKEND_PORT ..."
Write-Success "后端进程已启动"

# ---------- 5. 启动前端服务 ----------
Write-Info "========== 第四步：启动前端服务 =========="

# 等待后端端口就绪后再启动前端
$MaxWait = 10
for ($i = 1; $i -le $MaxWait; $i++) {
    Start-Sleep -Seconds 1
    $Connected = Test-NetConnection -ComputerName 127.0.0.1 -Port $BACKEND_PORT -WarningAction SilentlyContinue | Select-Object -ExpandProperty TcpTestSucceeded
    if ($Connected) {
        Write-Success "后端服务就绪（耗时 ${i} 秒）"
        break
    }
    if ($i -eq $MaxWait) {
        Write-Warn "等待后端就绪超时（${i} 秒），前端可能无法连接后端"
    }
}

# 启动前端 Vite 开发服务器（后台运行）
$FrontendProcess = Start-Process -FilePath "npm" `
    -ArgumentList "run", "dev" `
    -WorkingDirectory $FRONTEND_DIR `
    -PassThru `
    -WindowStyle Normal

Write-Info "前端启动中 (PID=$($FrontendProcess.Id))，端口 $FRONTEND_PORT ..."
Write-Success "前端进程已启动"

# ---------- 6. 总结 ----------
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  FlowerUI 开发环境已重启完成！" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  后端 API:    http://127.0.0.1:$BACKEND_PORT" -ForegroundColor White
Write-Host "  前端页面:    http://127.0.0.1:$FRONTEND_PORT" -ForegroundColor White
Write-Host "  模拟模式:    $(if ($Mock) { '已启用' } else { '已禁用' })" -ForegroundColor White
Write-Host ""
Write-Host "  后端日志:    $BACKEND_DIR\_uvicorn_*.log" -ForegroundColor Gray
Write-Host "  后端错误日志: $BACKEND_DIR\_uvicorn_err_*.log" -ForegroundColor Gray
Write-Host ""
Write-Host "  提示: 关闭此窗口不会停止服务（服务已在后台运行）" -ForegroundColor Yellow
Write-Host "  如需停止服务，请运行: Stop-Process -Name python -Force; Stop-Process -Name node -Force" -ForegroundColor Yellow
Write-Host ""

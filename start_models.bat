@echo off
setlocal enabledelayedexpansion
title 心迹 - 一键启动双模型
cd /d "%~dp0"

echo ============================================
echo   心迹 Psych Agent - 一键启动双模型
echo ============================================
echo.

REM ---------- 1. 选择 Python（优先项目 venv） ----------
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" --version >/dev/null 2>&1
if errorlevel 1 (
    echo [错误] 未找到可用的 Python。
    echo        请确认 .venv 存在，或系统中已安装 Python 并加入 PATH。
    pause
    exit /b 1
)
echo [1/4] Python 就绪

REM ---------- 2. 检查 Ollama ----------
where ollama >/dev/null 2>&1
if errorlevel 1 (
    echo [错误] 未找到 ollama 命令。
    echo        请先安装 Ollama：https://ollama.com/download
    pause
    exit /b 1
)
echo [2/4] Ollama 就绪

REM ---------- 3. 从配置读取两个模型名 ----------
set "SMALL="
set "LARGE="
for /f "delims=" %%i in ('"%PY%" -c "from config.model_config import GLOBAL_MODEL; print(GLOBAL_MODEL.small.ollama_name); print(GLOBAL_MODEL.large.ollama_name)"') do (
    if not defined SMALL (set "SMALL=%%i") else if not defined LARGE (set "LARGE=%%i")
)
if not defined SMALL set "SMALL=qwen2:1.5b"
if not defined LARGE set "LARGE=qwen3.5:9b-128k"

echo [3/4] 小模型: !SMALL!
echo       大模型: !LARGE!

REM ---------- 检查模型是否已拉取 ----------
ollama list | findstr /c:"!SMALL! " >/dev/null 2>&1
if errorlevel 1 (
    echo       [提示] 小模型 !SMALL! 尚未下载，启动后将自动拉取，请耐心等待。
)
ollama list | findstr /c:"!LARGE! " >/dev/null 2>&1
if errorlevel 1 (
    echo       [提示] 大模型 !LARGE! 尚未下载，启动后将自动拉取，请耐心等待。
)
echo.

REM ---------- 4. 打开两个模型窗口 ----------
start "SmallModel - !SMALL!" cmd /k ""%PY%" small_model_run.py"
start "LargeModel - !LARGE!" cmd /k ""%PY%" large_model_run.py"

echo [4/4] 已启动两个模型窗口：
echo   - 小模型：!SMALL!
echo   - 大模型：!LARGE!
echo.
echo 每个窗口内可直接输入对话，关闭窗口即退出该模型。
echo.
pause

@echo off
setlocal enabledelayedexpansion
title 心迹 - 启动后端服务
cd /d "%~dp0"

echo ============================================
echo   心迹 Psych Agent - 启动后端服务
echo ============================================
echo.

REM ===== 1. 选择可用的 Python（项目 venv 优先）=====
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY set "PY=python"
"%PY%" --version >/dev/null 2>&1
if errorlevel 1 (
    echo [错误] 未找到可用的 Python。
    echo        请确认 .venv 存在，或系统中已安装 Python 并加入 PATH。
    pause
    exit /b 1
)
for /f "delims=" %%v in ('"%PY%" --version 2^>^&1') do set "PYVER=%%v"
echo 使用 Python: %PY% (!PYVER!)

REM ===== 2. 允许 torch + MKL 的多线程库共存 =====
set "KMP_DUPLICATE_LIB_OK=TRUE"

REM ===== 3. 强制 Python 用 UTF-8 输出，避免日志里出现乱码 =====
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

REM ===== 4. 启动服务，日志写入 backend.log =====
echo 正在启动后端服务...
if exist backend.log del backend.log >/dev/null 2>&1
start "Xinji-Backend" /min cmd /c ""%PY%" main.py >> backend.log 2>&1"

REM ===== 5. 轮询等待服务就绪（最长 150 秒）=====
echo 等待服务就绪（约 60-120 秒），请稍候...
set /a tries=0
:waitloop
timeout /t 5 /nobreak >/dev/null
set /a tries+=1
set "code=000"
for /f "delims=" %%i in ('"%PY%" -c "import urllib.request,sys;
try:
    r=urllib.request.urlopen('http://127.0.0.1:8000/tool/model',timeout=2)
    print(r.status)
except Exception:
    print(0)" 2^>nul') do set "code=%%i"
if "!code!"=="200" goto ready
if %tries% GEQ 30 goto fail
echo   ...已等待 %tries% x 5 秒，服务尚未就绪，可查看 backend.log
goto waitloop

:ready
echo.
echo 服务已经就绪，正在打开页面...
start http://127.0.0.1:8000
exit /b 0

:fail
echo.
echo 服务启动超时（150 秒），请查看 backend.log 定位原因
pause
exit /b 1

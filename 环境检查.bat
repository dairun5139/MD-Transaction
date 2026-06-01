@echo off
chcp 65001 >nul
title 环境检查

echo ============================================
echo   蒙东电力交易规则智能问答系统 — 环境检查
echo ============================================
echo.

REM Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] Python 未安装或未加入 PATH
    echo        下载: https://www.python.org/downloads/
) else (
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo [OK]   %%i
)

REM Ollama
ollama list >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] Ollama 未安装或未启动
    echo        下载: https://ollama.com/
) else (
    echo [OK]   Ollama 已就绪
    for /f "tokens=*" %%i in ('ollama list 2^>^&1') do echo         %%i
)

echo.
echo ============================================
echo [详细检查]
echo ============================================
python check_env.py 2>nul
if %errorlevel% neq 0 (
    echo [WARN] check_env.py 执行失败，可能是依赖未安装
)

echo.
echo ============================================
echo   如果以上有 [MISS] 或 [FAIL] 项，请先解决后
echo   再双击"启动服务.bat"启动系统。
echo ============================================
pause

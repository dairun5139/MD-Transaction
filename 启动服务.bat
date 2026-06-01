@echo off
chcp 65001 >nul
title MD Transaction RAG 问答服务

echo ============================================
echo   蒙东电力交易规则智能问答系统
echo ============================================
echo.

REM 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo   当前 Python: %%i

REM 检查 Ollama
ollama list >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Ollama，请先安装并拉取模型
    echo 下载地址: https://ollama.com/
    echo 安装后运行:
    echo   ollama pull qwen2.5:7b
    echo   ollama pull nomic-embed-text
    echo.
    pause
    exit /b 1
)

REM 检查依赖
python -c "import fastapi" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [提示] 正在安装 Python 依赖（首次约需 1-2 分钟）...
    python -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败，请检查网络连接后重试
        echo.
        pause
        exit /b 1
    )
    echo [完成] 依赖安装成功
)

REM 环境检查
echo.
echo [检查] 正在检查环境配置...
python check_env.py
echo.

REM 启动服务
echo ============================================
echo [启动] 正在启动问答服务...
echo   浏览器将自动打开 http://127.0.0.1:8000/
echo   按 Ctrl+C 停止服务
echo ============================================
echo.
python api_app.py

pause

@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Inicializacao - Sistema de Gestao de Animais 1.0.0
set "PYTHONUTF8=1"
set "PIP_DEFAULT_TIMEOUT=120"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "LOG=%CD%\inicializacao.log"
set "MARKER=%CD%\.venv\.deps-v1.0.0-ok"

> "%LOG%" echo [%date% %time%] Inicio da inicializacao da versao 1.0.0.

echo ============================================================
echo        SISTEMA DE GESTAO DE ANIMAIS - VERSAO 1.0.0
echo ============================================================
echo.

set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py"
if not defined PYTHON_CMD (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo ERRO: O Python nao foi localizado neste computador.
    echo Instale o Python 3.10 ou superior e marque Add Python to PATH.
    >> "%LOG%" echo ERRO: Python nao localizado no PATH.
    pause
    exit /b 1
)

%PYTHON_CMD% --version >> "%LOG%" 2>&1
if errorlevel 1 goto :ERRO_PYTHON
%PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >> "%LOG%" 2>&1
if errorlevel 1 goto :ERRO_VERSAO

if not exist ".venv\Scripts\python.exe" (
    echo [1/6] Criando o ambiente do sistema...
    %PYTHON_CMD% -m venv ".venv" >> "%LOG%" 2>&1
    if errorlevel 1 goto :ERRO_VENV
) else (
    echo [1/6] Ambiente do sistema localizado.
)

echo [2/6] Preparando o instalador de componentes...
".venv\Scripts\python.exe" -m ensurepip --upgrade >> "%LOG%" 2>&1
".venv\Scripts\python.exe" -m pip install --upgrade pip --timeout 120 --retries 5 >> "%LOG%" 2>&1
if errorlevel 1 (
    echo AVISO: Nao foi possivel atualizar o pip. A instalacao continuara com a versao existente.
    >> "%LOG%" echo AVISO: Atualizacao do pip falhou; prosseguindo.
)

if exist "%MARKER%" (
    echo [3/6] Componentes ja instalados. Verificando integridade...
) else (
    echo [3/6] Instalando componentes locais. Isso pode levar alguns minutos...
    ".venv\Scripts\python.exe" -m pip install --prefer-binary --timeout 120 --retries 5 -r requirements-local.txt >> "%LOG%" 2>&1
    if errorlevel 1 goto :ERRO_DEPENDENCIAS
)

echo [4/6] Verificando componentes instalados...
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy, jinja2, multipart, dotenv, itsdangerous, alembic, openpyxl, reportlab; print('Componentes locais verificados com sucesso.')" >> "%LOG%" 2>&1
if errorlevel 1 goto :ERRO_DEPENDENCIAS
> "%MARKER%" echo 1.0.0

echo [5/6] Verificando configuracao e banco de dados...
".venv\Scripts\python.exe" scripts\check_environment.py >> "%LOG%" 2>&1
if errorlevel 1 goto :ERRO_CODIGO

echo [6/6] Iniciando o servidor local...
start "Servidor - Sistema de Gestao de Animais 1.0.0" "%CD%\SERVIDOR.bat"

echo Aguardando o sistema ficar disponivel...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$limite=(Get-Date).AddSeconds(120); do { try { $r=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 3; if ($r.status -eq 'ok') { exit 0 } } catch {}; Start-Sleep -Seconds 1 } while ((Get-Date) -lt $limite); exit 1" >> "%LOG%" 2>&1
if errorlevel 1 goto :ERRO_SERVIDOR

start "" "http://127.0.0.1:8000"
echo.
echo Sistema iniciado com sucesso.
echo Primeiro acesso local: usuario admin / senha admin12345
echo O sistema exigira a troca da senha.
echo Mantenha aberta a janela do servidor.
echo.
timeout /t 7 >nul
exit /b 0

:ERRO_PYTHON
echo ERRO: O Python foi localizado, mas nao esta funcionando.
goto :ERRO_FINAL
:ERRO_VERSAO
echo ERRO: E necessario Python 3.10 ou superior.
goto :ERRO_FINAL
:ERRO_VENV
echo ERRO: Nao foi possivel criar o ambiente virtual.
goto :ERRO_FINAL
:ERRO_DEPENDENCIAS
echo.
echo ERRO: Nao foi possivel instalar ou validar os componentes.
echo A causa exata esta nas ultimas linhas abaixo:
echo ------------------------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Path '%LOG%' -Tail 35" 2>nul
echo ------------------------------------------------------------
echo Execute REPARAR_INSTALACAO.bat para refazer o ambiente do zero.
goto :ERRO_FINAL
:ERRO_CODIGO
echo ERRO: A configuracao ou a conexao com o banco falhou.
goto :ERRO_FINAL
:ERRO_SERVIDOR
echo ERRO: O servidor nao iniciou dentro do prazo esperado.
:ERRO_FINAL
echo Consulte tambem o arquivo inicializacao.log.
pause
exit /b 1

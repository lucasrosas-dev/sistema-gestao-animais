@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Reparacao - Sistema de Gestao de Animais 1.0.0

echo ============================================================
echo        REPARACAO DA INSTALACAO - VERSAO 1.0.0
echo ============================================================
echo.
echo Este procedimento apaga somente o ambiente Python .venv.
echo O banco de dados da pasta data NAO sera apagado.
echo.
choice /C SN /N /M "Deseja continuar? [S/N]: "
if errorlevel 2 exit /b 0

if exist ".venv" (
    echo Removendo ambiente incompleto...
    rmdir /S /Q ".venv"
    if exist ".venv" (
        echo ERRO: Nao foi possivel remover .venv.
        echo Feche janelas do servidor e tente novamente.
        pause
        exit /b 1
    )
)
if exist "inicializacao.log" del /Q "inicializacao.log"
echo Ambiente removido. Iniciando nova instalacao...
call "%CD%\INICIAR_SISTEMA.bat"

@echo off
setlocal
cd /d "%~dp0"
title Servidor - Sistema de Gestao de Animais 1.0.0

echo ============================================================
echo   SERVIDOR DO SISTEMA DE GESTAO DE ANIMAIS - VERSAO 1.0.0
echo ============================================================
echo.
echo Mantenha esta janela aberta enquanto utilizar o sistema.
echo Endereco: http://127.0.0.1:8000
echo Para encerrar, pressione Ctrl+C ou feche esta janela.
echo.

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo.
echo O servidor foi encerrado ou ocorreu um erro.
echo Consulte inicializacao.log e execute DIAGNOSTICO.bat.
pause

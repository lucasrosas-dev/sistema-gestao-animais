@echo off
setlocal
cd /d "%~dp0"
title Diagnostico - Sistema de Gestao de Animais 1.0.0
set "ARQUIVO=%CD%\diagnostico.txt"
> "%ARQUIVO%" echo DIAGNOSTICO DO SISTEMA 1.0.0 - %date% %time%
>> "%ARQUIVO%" echo Pasta: %CD%
>> "%ARQUIVO%" echo.
echo Verificando instalacao. Aguarde...
>> "%ARQUIVO%" echo ===== PYTHON =====
where py >> "%ARQUIVO%" 2>&1
py --version >> "%ARQUIVO%" 2>&1
where python >> "%ARQUIVO%" 2>&1
python --version >> "%ARQUIVO%" 2>&1
>> "%ARQUIVO%" echo.
>> "%ARQUIVO%" echo ===== AMBIENTE VIRTUAL =====
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" --version >> "%ARQUIVO%" 2>&1
    ".venv\Scripts\python.exe" -m pip --version >> "%ARQUIVO%" 2>&1
    ".venv\Scripts\python.exe" -m pip check >> "%ARQUIVO%" 2>&1
    ".venv\Scripts\python.exe" -c "import fastapi,uvicorn,sqlalchemy,jinja2,multipart,dotenv,itsdangerous,alembic,openpyxl,reportlab; print('Imports principais: OK')" >> "%ARQUIVO%" 2>&1
    ".venv\Scripts\python.exe" scripts\check_environment.py >> "%ARQUIVO%" 2>&1
) else (
    >> "%ARQUIVO%" echo Ambiente virtual ainda nao criado.
)
>> "%ARQUIVO%" echo.
>> "%ARQUIVO%" echo ===== ULTIMAS LINHAS DA INICIALIZACAO =====
if exist "inicializacao.log" powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Path 'inicializacao.log' -Tail 80" >> "%ARQUIVO%" 2>&1
>> "%ARQUIVO%" echo.
>> "%ARQUIVO%" echo ===== PORTA 8000 =====
netstat -ano | findstr ":8000" >> "%ARQUIVO%" 2>&1
>> "%ARQUIVO%" echo.
>> "%ARQUIVO%" echo ===== TESTE HTTP =====
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 3 | ConvertTo-Json } catch { $_.Exception.Message; exit 1 }" >> "%ARQUIVO%" 2>&1
echo.
echo Diagnostico concluido: %ARQUIVO%
start "" notepad "%ARQUIVO%"
pause

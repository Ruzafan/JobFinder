@echo off
echo ========================================================
echo        JobFinder CV Studio - Inicio Local
echo ========================================================
echo.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] Creando entorno virtual con Python 3.13...
    py -3.13 -m venv .venv
    echo [2/2] Instalando dependencias necesarias...
    .\.venv\Scripts\pip install -r requirements.txt
)

echo.
echo Iniciando servidor en http://localhost:8000
echo Acceso desde movil u otros dispositivos: http://192.168.1.149:8000
echo (Presiona Ctrl+C para detener el servidor)
echo.

.\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

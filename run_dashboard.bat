@echo off
REM ============================================================
REM  Dashboard Black Point Roma
REM  Doppio click per avviare la dashboard interattiva.
REM  Poi apri il browser su: http://localhost:8050
REM ============================================================

cd /d "%~dp0"

echo.
echo  ============================================================
echo   Black Point Roma - Avvio dashboard
echo  ============================================================
echo.

python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERRORE] Python non trovato nel PATH.
    pause
    exit /b 1
)

REM Installa le dipendenze se mancanti (tutte, da requirements.txt:
REM la dashboard usa anche pysal/esda per gli indici di equita').
echo  Verifica dipendenze...
python -m pip install -r requirements.txt --quiet

echo.
echo  Avvio dashboard su http://localhost:8050
echo  Premi CTRL+C per fermare il server.
echo.

python -m dashboard.app

pause

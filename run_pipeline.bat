@echo off
REM ============================================================
REM  Pipeline Black Point Roma - Orchestratore Windows
REM  Doppio click su questo file per eseguire tutta la pipeline.
REM  Oppure dal terminale: run_pipeline.bat
REM ============================================================

SETLOCAL ENABLEDELAYEDEXPANSION

REM Spostati nella cartella radice del progetto (quella che contiene questo file)
cd /d "%~dp0"

echo.
echo  ============================================================
echo   Black Point Roma - Avvio pipeline
echo  ============================================================
echo.

REM Verifica che Python sia disponibile
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERRORE] Python non trovato. Assicurati che Python sia installato
    echo          e presente nel PATH di sistema.
    pause
    exit /b 1
)

REM Lista degli step in ordine
SET STEPS=src.s00_pulizia_incidenti src.s01_preparazione_rete src.s02_matching src.s03_spf src.s04_empirical_bayes src.s05_indice_composito src.s06_export

FOR %%S IN (%STEPS%) DO (
    echo.
    echo  ----------------------------------------------------------
    echo   Esecuzione: %%S
    echo  ----------------------------------------------------------
    python -m %%S
    IF ERRORLEVEL 1 (
        echo.
        echo [ERRORE] Lo step %%S ha restituito un errore. Pipeline interrotta.
        pause
        exit /b 1
    )
    echo   [OK] %%S completato.
)

echo.
echo  ============================================================
echo   Pipeline completata con successo.
echo  ============================================================
echo.
pause

@echo off
REM ============================================================
REM  Pipeline Black Point Roma / PSS - Orchestratore Windows
REM  Doppio click su questo file per eseguire tutta la pipeline.
REM  Oppure dal terminale: run_pipeline.bat
REM ============================================================

SETLOCAL ENABLEDELAYEDEXPANSION

REM Spostati nella cartella radice del progetto
cd /d "%~dp0"

echo.
echo  ============================================================
echo   Black Point Roma / PSS - Avvio pipeline
echo  ============================================================
echo.

python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERRORE] Python non trovato. Assicurati che Python sia installato
    echo          e presente nel PATH di sistema.
    pause
    exit /b 1
)

REM --- Step condizionali (moduli PSS: girano solo se i dati ci sono) ---
IF EXIST "data\raw\censimento\Sezioni_ISTAT.gpkg" (
    echo  ----------------------------------------------------------
    echo   Esecuzione: src.s0c_censimento
    echo  ----------------------------------------------------------
    python -m src.s0c_censimento
    IF ERRORLEVEL 1 GOTO :errore
)
IF EXIST "data\raw\progetti" (
    echo  ----------------------------------------------------------
    echo   Esecuzione: src.s0d_interventi
    echo  ----------------------------------------------------------
    python -m src.s0d_interventi
    IF ERRORLEVEL 1 GOTO :errore
)

REM --- Pipeline principale (s07 tra s05 e s06) ---
SET STEPS=src.s00_pulizia_incidenti src.s01_preparazione_rete src.s02_matching src.s03_spf src.s04_empirical_bayes src.s05_indice_composito src.s07_hin src.s06_export

FOR %%S IN (%STEPS%) DO (
    echo.
    echo  ----------------------------------------------------------
    echo   Esecuzione: %%S
    echo  ----------------------------------------------------------
    python -m %%S
    IF ERRORLEVEL 1 GOTO :errore
    echo   [OK] %%S completato.
)

REM --- Moduli PSS a valle (equita', scenari, valutazione) ---
IF EXIST "data\interim\censimento_prep.gpkg" IF EXIST "data\interim\interventi_prep.gpkg" (
    FOR %%S IN (src.s08_equita src.s09_ottimizzazione src.s10_valutazione) DO (
        echo.
        echo  ----------------------------------------------------------
        echo   Esecuzione: %%S
        echo  ----------------------------------------------------------
        python -m %%S
        IF ERRORLEVEL 1 GOTO :errore
        echo   [OK] %%S completato.
    )
)

echo.
echo  ============================================================
echo   Pipeline completata con successo.
echo  ============================================================
echo.
pause
exit /b 0

:errore
echo.
echo [ERRORE] Uno step ha restituito un errore. Pipeline interrotta.
pause
exit /b 1

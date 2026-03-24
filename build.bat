@echo off
REM ============================================================
REM  build.bat  -  Compila Memento con PyInstaller e prepara
REM               i file per l'installer Inno Setup.
REM
REM  Utilizzo: eseguire dalla directory principale del progetto
REM            con l'ambiente virtuale attivato, oppure lasciare
REM            che lo script lo attivi automaticamente.
REM ============================================================

setlocal

REM -- Attivazione ambiente virtuale (se presente) -------------
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

REM -- Verifica PyInstaller ------------------------------------
where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] PyInstaller non trovato. Installalo con:
    echo          pip install pyinstaller
    exit /b 1
)

REM -- Pulizia build precedente --------------------------------
echo Pulizia cartelle build\  e dist\ ...
if exist "build" rmdir /s /q "build"
if exist "dist"  rmdir /s /q "dist"

REM -- Build applicazione principale ---------------------------
echo.
echo === Build Memento (app principale) ===
pyinstaller Memento.spec --noconfirm
if errorlevel 1 (
    echo [ERRORE] Build di Memento fallita.
    exit /b 1
)

REM -- Build demone tray ---------------------------------------
echo.
echo === Build MementoTray (icona tray) ===
pyinstaller MementoTray.spec --noconfirm
if errorlevel 1 (
    echo [ERRORE] Build di MementoTray fallita.
    exit /b 1
)

REM -- Copia MementoTray nella cartella di Memento -------------
REM    L'installer Inno Setup usa dist\Memento\ come sorgente
REM    unica; MementoTray.exe deve trovarsi nella stessa dir.
echo.
echo Copia MementoTray.exe in dist\Memento\ ...
xcopy /s /y /i "dist\MementoTray\*" "dist\Memento\" >nul

REM -- Patch icona flet (per il pin sulla barra applicazioni) --
echo.
echo Patch icona in flet_desktop\app\flet\flet.exe ...
python patch_icon.py "dist\Memento\_internal\flet_desktop\app\flet\flet.exe" "Images\memento.ico"
if errorlevel 1 (
    echo [AVVISO] Patch icona flet fallita, ma la build continua.
)

echo.
echo ============================================================
echo  Build completata.
echo  Eseguibile principale : dist\Memento\Memento.exe
echo  Eseguibile tray        : dist\Memento\MementoTray.exe
echo.
echo  Passo successivo: apri installer\Memento_Setup.iss con
echo  Inno Setup e compila per generare il file di installazione.
echo ============================================================

endlocal

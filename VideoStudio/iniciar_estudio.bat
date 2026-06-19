@echo off
title Estudio de Video IA  (cierra esta ventana para apagar)
echo ============================================
echo    ESTUDIO DE VIDEO IA  -  100%% LOCAL
echo    Encendiendo... se abrira en tu navegador.
echo ============================================
start "browser" cmd /c "timeout /t 5 >nul & start http://127.0.0.1:5000"
python "C:\AI\VideoStudio\webapp\app.py"
pause

@echo off
title Estudio de Video IA  (cierra esta ventana para apagar el servidor)
echo ============================================
echo   ESTUDIO DE VIDEO IA - 100%% LOCAL
echo   Abriendo en tu navegador...
echo ============================================
start "browser" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:5000"
python "C:\AI\VideoStudio\webapp\app.py"
pause

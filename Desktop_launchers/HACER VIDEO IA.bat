@echo off
setlocal enabledelayedexpansion
title Generador de Video IA Local (LTX)
color 0b
echo ============================================
echo    GENERADOR DE VIDEO IA LOCAL  (RTX 3070)
echo ============================================
echo.
echo Escribe tu idea EN INGLES (los modelos entienden mejor ingles).
echo Ejemplo: a cat astronaut floating in space, cinematic, 4k
echo.
set /p PROMPT="Tu video: "
echo.
echo (Opcional) Agrega FOTOS-ANCLA en orden (1ra = inicio, ultima = final).
echo Arrastra una foto aqui y Enter. Deja vacio y Enter para terminar.
echo Mas fotos = video mas largo y SIN partes raras. (0 fotos = solo texto)
echo.
set "IMGS="
set /a NUM=0
:askimg
set /a NUM+=1
set "ONE="
set /p "ONE=Foto #!NUM! (Enter=terminar): "
if defined ONE (
  set "ONE=!ONE:"=!"
  if defined IMGS ( set "IMGS=!IMGS!;!ONE!" ) else ( set "IMGS=!ONE!" )
  goto askimg
)
echo.
if defined IMGS (
  powershell -ExecutionPolicy Bypass -File "C:\AI\HACER_VIDEO.ps1" -Prompt "!PROMPT!" -ImagenesStr "!IMGS!"
) else (
  powershell -ExecutionPolicy Bypass -File "C:\AI\HACER_VIDEO.ps1" -Prompt "!PROMPT!"
)
echo.
pause

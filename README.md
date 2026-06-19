# 🎬 Estudio de Video IA — Local

App 100% local para crear reels / videos verticales con IA, corriendo en una **RTX 3070**.
Genera voz (edge-tts), subtítulos, y clips de video con **ComfyUI + LTX-Video**, y los une en un reel final.

Este repo es el **respaldo del código fuente** antes de empezar a mejorarlo.

## Estructura

```
VideoStudio/
  ESTUDIO.ps1            # lanzador principal (PowerShell)
  lib.ps1                # funciones compartidas
  iniciar_estudio.bat    # arranque
  estudio_icon.ico       # icono custom de la app
  webapp/
    app.py               # servidor Flask (http://127.0.0.1:5000)
    templates/index.html # interfaz web
  proyectos/             # metadata de proyectos (los .mp4/.mp3 NO se versionan)

AI_root_scripts/
  HACER_VIDEO.ps1        # generador directo (prompt + fotos-ancla -> video LTX)
  ltx_t2v_prompt.json    # plantilla de prompt para LTX text-to-video
  organizar_modelos.ps1  # acomoda los modelos de ComfyUI

Desktop_launchers/       # accesos directos y .bat del escritorio
```

## Lo que NO está en el repo (a propósito)

- **ComfyUI** (`C:\AI\ComfyUI_windows_portable`, ~51 GB) — el motor de IA, se reinstala aparte.
- `ComfyUI_portable.7z` (~1.9 GB) y modelos (`.safetensors`/`.ckpt`).
- Videos/audio renderizados (`.mp4`, `.mp3`, `.wav`) — son salida reproducible.

## Rutas originales en la PC

- Código: `C:\AI\VideoStudio\` y scripts en `C:\AI\`
- Motor: `C:\AI\ComfyUI_windows_portable\`

---
Respaldo creado: 2026-06-19

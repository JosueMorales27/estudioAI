# 🎬 Estudio de Video IA — Repo de trabajo

Repositorio **en vivo** del código (`C:\AI`). Aquí editamos y mejoramos el programa.
App 100% local para reels con IA en una **RTX 3070** (voz edge-tts + subtítulos + ComfyUI/LTX-Video).

## Qué versiona este repo
- `VideoStudio/` — app principal: `ESTUDIO.ps1`, `lib.ps1`, `webapp/app.py`, `templates/index.html`
- `HACER_VIDEO.ps1`, `ltx_t2v_prompt.json`, `organizar_modelos.ps1` — generadores/utilidades

## Qué NO versiona (ver `.gitignore`)
- `ComfyUI_windows_portable/` (~51 GB) y `*.7z` / modelos — el motor, se reinstala aparte
- Videos/audio renderizados (`.mp4`, `.mp3`, `.wav`) — salida reproducible
- `_backups/`, `__pycache__/`, logs

## 🔙 Cómo regresarnos si rompemos algo

**Ver el historial:**
```powershell
cd C:\AI
git log --oneline
```

**Deshacer cambios NO guardados (volver al último commit):**
```powershell
git restore .            # descarta cambios en archivos
git clean -fd            # borra archivos nuevos no rastreados (ojo)
```

**Regresar TODO a un commit anterior (sin perder historial):**
```powershell
git revert <hash>        # crea un commit que deshace ese cambio
```

**Regresar a un punto exacto (rebobinar duro — usar con cuidado):**
```powershell
git reset --hard <hash>
```

**Volver al respaldo inicial completo:**
```powershell
git checkout respaldo-inicial-2026-06-19
```

## 💾 Guardar avances (backup en GitHub)
```powershell
cd C:\AI
git add -A
git commit -m "describe el cambio"
git push
```

---
Remoto: https://github.com/JosueMorales27/estudioAI
Rama de respaldo intacto: `respaldo-inicial-2026-06-19`

# -*- coding: utf-8 -*-
"""
ESTUDIO DE VIDEO IA  -  App web local tipo ChatGPT  (v2 - motor cinematografico)
100% local / open source. NO usa Claude ni APIs de pago.

QUE HACE:
  - Modo FOTOS  -> motor IA: cada foto COBRA VIDA con movimiento generado por
                   LTX-Video (ComfyUI en tu GPU). Reparte el parrafo entre TODAS
                   tus fotos (todas se animan), une todos los clips y encima la
                   voz COMPLETA: el audio nunca se corta. (Ken Burns queda solo
                   como respaldo de emergencia si la GPU esta apagada.)
  - Modo TEXTO  -> genera clips con LTX-Video (ComfyUI en tu GPU) y los estira a
                   la duracion de su voz (sin cortes).
  - Voz con edge-tts (es-MX/es-US/es-ES, gratis) + subtitulos RODANTES quemados.
  - Une todo con ffmpeg y exporta en el formato que elijas (9:16 / 1:1 / 16:9).
  - Cada resultado queda ORGANIZADO en:  Escritorio\\Estudio de Video IA\\<proyecto>\\
"""
import os, re, json, time, uuid, threading, subprocess, math, shutil, urllib.request
from flask import Flask, request, jsonify, send_file

# ---------------- Config ----------------
COMFY      = "http://127.0.0.1:8188"
COMFY_ROOT = r"C:\AI\ComfyUI_windows_portable\ComfyUI"
COMFY_OUT  = os.path.join(COMFY_ROOT, "output")
COMFY_IN   = os.path.join(COMFY_ROOT, "input")
PROYECTOS  = r"C:\AI\VideoStudio\proyectos"
DESKTOP    = os.path.join(os.path.expanduser("~"), "Desktop")
SALIDA_RAIZ= os.path.join(DESKTOP, "Estudio de Video IA")   # carpeta organizada
FONT_SRC   = r"C:\Windows\Fonts\arialbd.ttf"
CKPT       = "ltx-video-2b-v0.9.5.safetensors"
T5         = "t5xxl_fp8_e4m3fn_scaled.safetensors"
FPS        = 30                       # fps de salida (suave)
CHARS_POR_CLIP = 95                   # ~5 s de narracion (solo modo TEXTO)
MAX_SEG_CLIP   = 7                    # tope LTX por VRAM 8GB (solo modo TEXTO)

# Formatos de salida (W, H)
FORMATOS = {
    "vertical":   (1080, 1920),   # 9:16  TikTok / Reels / Shorts
    "cuadrado":   (1080, 1080),   # 1:1   feed
    "horizontal": (1920, 1080),   # 16:9  YouTube
}
PY = __import__("sys").executable

app = Flask(__name__)
JOBS = {}   # job_id -> dict(estado, progreso, mensajes[], video, error, carpeta)

# ---------------- utilidades ----------------
def log(job, msg):
    JOBS[job]["mensajes"].append(msg)
    print(f"[{job[:6]}] {msg}", flush=True)

def comfy_vivo():
    try:
        urllib.request.urlopen(COMFY + "/system_stats", timeout=3); return True
    except Exception:
        return False

def ffprobe_dur(path):
    try:
        out = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                              "-of","csv=p=0",path], capture_output=True, text=True)
        return float(out.stdout.strip())
    except Exception:
        return 0.0

def run(cmd):
    """Corre ffmpeg/ffprobe y devuelve (ok, stderr). Captura todo para depurar."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode == 0, (p.stderr or "")

def slug(texto, n=5):
    palabras = re.findall(r"[A-Za-z0-9ÁÉÍÓÚáéíóúÑñ]+", texto)[:n]
    s = "_".join(palabras).lower() or "video"
    return s[:40]

def carpeta_proyecto(texto):
    r"""Crea Escritorio\Estudio de Video IA\<fecha_hora>_<slug>\ y la regresa."""
    os.makedirs(SALIDA_RAIZ, exist_ok=True)
    nombre = time.strftime("%Y-%m-%d_%H%M") + "_" + slug(texto)
    dest = os.path.join(SALIDA_RAIZ, nombre)
    i = 2
    while os.path.exists(dest):
        dest = os.path.join(SALIDA_RAIZ, f"{nombre}_{i}"); i += 1
    os.makedirs(dest, exist_ok=True)
    return dest

# ---------------- division de texto (modo TEXTO) ----------------
def dividir_parrafo(texto, limite=CHARS_POR_CLIP):
    """Divide un parrafo en segmentos de ~limite caracteres respetando frases."""
    texto = texto.strip()
    piezas = re.split(r'(?<=[\.\!\?\n])\s+', texto)
    frases = []
    for p in piezas:
        p = p.strip()
        if not p: continue
        if len(p) <= limite:
            frases.append(p)
        else:
            sub = re.split(r'(?<=,)\s+', p)
            buf = ""
            for s in sub:
                if len(buf) + len(s) + 1 <= limite:
                    buf = (buf + " " + s).strip()
                else:
                    if buf: frases.append(buf)
                    if len(s) <= limite:
                        buf = s
                    else:
                        palabras = s.split()
                        buf = ""
                        for w in palabras:
                            if len(buf) + len(w) + 1 <= limite:
                                buf = (buf + " " + w).strip()
                            else:
                                if buf: frases.append(buf)
                                buf = w
            if buf: frases.append(buf)
    segmentos, buf = [], ""
    for f in frases:
        if len(buf) + len(f) + 1 <= limite:
            buf = (buf + " " + f).strip()
        else:
            if buf: segmentos.append(buf)
            buf = f
    if buf: segmentos.append(buf)
    return segmentos or [texto[:limite]]

def repartir_texto(texto, n):
    """Parte el texto en n trozos balanceados por palabras. Sirve para repartir
    el parrafo entre las fotos: cada foto recibe un trozo que guia su movimiento.
    Si hay menos palabras que trozos, cada trozo usa el texto completo (nunca vacio)."""
    texto = texto.strip()
    if n <= 1:
        return [texto]
    words = texto.split()
    if len(words) < n:
        return [texto for _ in range(n)]
    per = len(words) / n
    chunks = []
    for i in range(n):
        a = int(round(i * per)); b = int(round((i + 1) * per))
        chunks.append(" ".join(words[a:b]).strip() or texto)
    return chunks

# ---------------- subtitulos ----------------
def srt_ts(seg):
    h = int(seg // 3600); m = int((seg % 3600)//60); s = int(seg % 60); ms = int(round((seg-int(seg))*1000))
    if ms == 1000: s += 1; ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def trocear_para_subs(texto, max_chars=38):
    """Parte el texto en lineas cortas legibles (corta en palabras)."""
    # primero por frases para no romper a media idea
    frases = re.split(r'(?<=[\.\!\?])\s+', texto.strip())
    chunks = []
    for fr in frases:
        words = fr.split()
        buf = ""
        for w in words:
            if len(buf) + len(w) + 1 <= max_chars:
                buf = (buf + " " + w).strip()
            else:
                if buf: chunks.append(buf)
                buf = w
        if buf: chunks.append(buf)
    return [c for c in chunks if c]

def srt_rodante(texto, dur_total, t0=0.0):
    """Genera lineas SRT que ruedan a lo largo de dur_total, repartiendo el tiempo
    proporcional a la longitud de cada trozo (subtitulos sincronizados con la voz)."""
    chunks = trocear_para_subs(texto)
    if not chunks: return [], 1
    total_chars = sum(len(c) for c in chunks) or 1
    lines = []; t = t0; idx = 1
    for c in chunks:
        d = dur_total * (len(c) / total_chars)
        d = max(0.9, d)  # nada parpadea demasiado rapido
        lines.append(f"{idx}\n{srt_ts(t)} --> {srt_ts(t + d)}\n{c}\n")
        t += d; idx += 1
    return lines, idx - 1

# ---------------- subtitulos KARAOKE en formato ASS (tamano real, palabra x palabra) -------
def _ass_ts(seg):
    """Timestamp ASS: H:MM:SS.cc (centisegundos)."""
    if seg < 0: seg = 0
    h = int(seg // 3600); m = int((seg % 3600) // 60); s = int(seg % 60)
    cs = int(round((seg - int(seg)) * 100))
    if cs == 100: s += 1; cs = 0
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def _ass_safe(t):
    """Evita que llaves del texto rompan el parseo ASS."""
    return t.replace("{", "(").replace("}", ")").replace("\n", " ").strip()

def _ass_header(W, H):
    """Cabecera ASS con resolucion REAL (PlayResX/Y = WxH) -> el Fontsize es en
    pixeles reales, no escalado raro. Subtitulos abajo, centrados, en zona segura."""
    base = min(W, H)                       # lado corto -> mismo tamano en 9:16, 1:1, 16:9
    fs   = max(18, int(base * 0.045))      # letra real, legible pero NO invasiva
    mv   = int(H * 0.11)                   # sube los subs del borde -> zona inferior segura
    ml   = mr = int(W * 0.07)
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        f"PlayResX: {W}\nPlayResY: {H}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Sub,Arial,{fs},&H00FFFFFF,&H0000D7FF,&H00101010,&H64000000,"
        f"1,0,0,0,100,100,0,0,1,3,1,2,{ml},{mr},{mv},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

def _ass_eventos(texto, dur_total, t0=0.0):
    """Eventos karaoke: cada frase corta revela sus palabras UNA POR UNA (sincronizadas
    con la voz) y al terminar la frase desaparece sola. Devuelve lista de 'Dialogue:'."""
    chunks = trocear_para_subs(texto, max_chars=30)   # frases cortas, estilo reel
    if not chunks: return []
    total_chars = sum(len(c) for c in chunks) or 1
    eventos = []; t = t0
    for c in chunks:
        d = max(0.9, dur_total * (len(c) / total_chars))   # cuanto dura esta frase
        words = c.split()
        wchars = sum(len(w) for w in words) or 1
        wt = t
        for k, w in enumerate(words):
            wd = max(0.14, d * (len(w) / wchars))          # tiempo de esta palabra
            fin = t + d if k == len(words) - 1 else min(t + d, wt + wd)
            visible = _ass_safe(" ".join(words[:k + 1]))   # acumulado: van apareciendo
            eventos.append(f"Dialogue: 0,{_ass_ts(wt)},{_ass_ts(fin)},Sub,,0,0,0,,{visible}")
            wt = fin
        t += d
    return eventos

def escribir_ass(path, W, H, eventos):
    with open(path, "w", encoding="utf-8") as f:
        f.write(_ass_header(W, H))
        f.write("\n".join(eventos) + "\n")

# ---------------- MOTOR CINE: Ken Burns + transiciones (modo FOTOS) ----------------
def _zoompan_para(idx, di, W, H):
    """Devuelve la cadena de filtros para animar UNA foto con zoom/paneo HD.
    Alterna el tipo de movimiento por indice para dar variedad cinematografica."""
    frames = max(1, int(round(di * FPS)))
    f = frames
    # lienzo grande (2x) para que el zoom no pixele ni tiemble
    base = f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},setsar=1"
    # Para que el PANEO se note de verdad necesitamos zoom alto: con zoom~1.0 el
    # recorrido (iw-iw/zoom) es casi 0 y el paneo era invisible (parecia solo zoom).
    # En los modos de paneo fijamos zoom=1.30 -> hay margen real para deslizarse.
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"   # centrado
    # 'ease' = avance suave 0->1 con aceleracion/frenado (curva coseno), camara real
    ease  = f"(1-cos(PI*on/{f}))/2"
    easeI = f"(1+cos(PI*on/{f}))/2"                   # inverso (1->0) para paneos al reves
    modo = idx % 6
    if modo == 0:      # zoom in lento, centrado
        z, x, y = "min(zoom+0.0015,1.30)", cx, cy
    elif modo == 1:    # paneo horizontal: izquierda -> derecha
        z, x, y = "1.30", f"(iw-iw/zoom)*{ease}", cy
    elif modo == 2:    # paneo horizontal: derecha -> izquierda
        z, x, y = "1.30", f"(iw-iw/zoom)*{easeI}", cy
    elif modo == 3:    # paneo vertical: arriba -> abajo
        z, x, y = "1.30", cx, f"(ih-ih/zoom)*{ease}"
    elif modo == 4:    # paneo diagonal con zoom in
        z, x, y = "min(zoom+0.0012,1.35)", f"(iw-iw/zoom)*{ease}", f"(ih-ih/zoom)*{ease}"
    else:              # zoom out (empieza acercado y se aleja)
        z, x, y = "if(eq(on,0),1.30,max(zoom-0.0015,1.0))", cx, cy
    zp = (f"zoompan=z='{z}':x='{x}':y='{y}':d={f}:s={W}x{H}:fps={FPS}")
    return f"{base},{zp},format=yuv420p"

def kenburns(imagenes, dur_total, W, H, out_file, job=None):
    """Crea un video HD (WxH) de duracion EXACTA dur_total recorriendo TODAS las
    fotos en orden, con zoom/paneo y transiciones cruzadas. Usa SOLO las fotos
    dadas: cero alucinaciones. Devuelve out_file o None."""
    imgs = [p for p in imagenes if p and os.path.exists(p)]
    if not imgs:
        return None
    n = len(imgs)
    # NOTA: cada foto se pasa como UNA sola imagen (1 frame). zoompan genera 'd'
    # frames a partir de ese frame. NO usar -loop: alimentaria frames infinitos y
    # la duracion se dispararia (bug). La duracion la fija d=frames a FPS.
    if n == 1:
        fc = "[0:v]" + _zoompan_para(0, dur_total, W, H) + "[v]"
        ok, err = run(["ffmpeg","-y","-i",imgs[0],
                       "-filter_complex",fc,"-map","[v]","-r",str(FPS),"-t",f"{dur_total:.3f}",
                       "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",out_file])
        if not ok and job: log(job, "  (kenburns 1 foto) " + err[-200:])
        return out_file if ok else None

    # transicion cruzada tr; cada foto dura di; total tras solapes = dur_total
    tr = max(0.5, min(1.0, dur_total / (n * 3.0)))
    di = (dur_total + (n - 1) * tr) / n
    di = max(di, tr + 0.6)
    transiciones = ["fade","smoothleft","smoothright","wipeleft","circlecrop","fadeblack","slideup"]

    cmd = ["ffmpeg","-y"]
    for p in imgs:
        cmd += ["-i",p]      # 1 frame por foto; zoompan (d=frames) define la duracion
    parts = []
    for i in range(n):
        parts.append(f"[{i}:v]{_zoompan_para(i, di, W, H)}[v{i}]")
    # cadena xfade
    prev = "v0"; offset = di - tr
    for i in range(1, n):
        outl = f"x{i}" if i < n - 1 else "v"
        trn = transiciones[(i - 1) % len(transiciones)]
        parts.append(f"[{prev}][v{i}]xfade=transition={trn}:duration={tr:.3f}:offset={offset:.3f}[{outl}]")
        prev = outl; offset += di - tr
    fc = ";".join(parts)
    ok, err = run(cmd + ["-filter_complex",fc,"-map","[v]","-r",str(FPS),
                          "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",out_file])
    if not ok:
        if job: log(job, "  (kenburns multi) " + err[-240:])
        return None
    return out_file

# ---------------- generacion de un clip LTX via ComfyUI (modo TEXTO) ----------------
def _snap8(f):
    return 0 if f <= 0 else ((f - 1) // 8) * 8 + 1

def _largo_auto(segundos):
    segundos = min(MAX_SEG_CLIP, max(2, segundos or 4))
    return max(9, int(math.floor((segundos * 25) / 8) * 8 + 1))   # LTX corre a 25 fps internos

def generar_clip_ltx(prompt, segundos, imagen_guia, out_file):
    """Genera un clip LTX. imagen_guia (opcional) ancla el 1er frame (continuidad)."""
    length = _largo_auto(segundos)
    seed = uuid.uuid4().int % 2147483000
    neg = "blurry, low quality, distorted, deformed, static, watermark, text, jpeg artifacts"
    g = {
        "1": {"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":CKPT}},
        "2": {"class_type":"CLIPLoader","inputs":{"clip_name":T5,"type":"ltxv"}},
        "3": {"class_type":"CLIPTextEncode","inputs":{"text":prompt,"clip":["2",0]}},
        "4": {"class_type":"CLIPTextEncode","inputs":{"text":neg,"clip":["2",0]}},
        "6": {"class_type":"ModelSamplingLTXV","inputs":{"model":["1",0],"max_shift":2.05,"base_shift":0.95}},
        "9": {"class_type":"KSamplerSelect","inputs":{"sampler_name":"euler"}},
        "8": {"class_type":"LTXVScheduler","inputs":{"steps":30,"max_shift":2.05,"base_shift":0.95,"stretch":True,"terminal":0.1}},
        "12":{"class_type":"CreateVideo","inputs":{"images":["11",0],"fps":25}},
        "13":{"class_type":"SaveVideo","inputs":{"video":["12",0],"filename_prefix":"estudio_web/clip","format":"mp4","codec":"h264"}},
        "7": {"class_type":"EmptyLTXVLatentVideo","inputs":{"width":768,"height":512,"length":length,"batch_size":1}},
    }
    if imagen_guia and os.path.exists(imagen_guia):
        name = f"webkf_{uuid.uuid4().hex}_{os.path.basename(imagen_guia)}"
        shutil.copy(imagen_guia, os.path.join(COMFY_IN, name))
        g["20"]={"class_type":"LoadImage","inputs":{"image":name}}
        g["30"]={"class_type":"LTXVAddGuide","inputs":{"positive":["3",0],"negative":["4",0],"vae":["1",2],"latent":["7",0],"image":["20",0],"frame_idx":0,"strength":1.0}}
        g["8"]["inputs"]["latent"]=["30",2]
        g["10"]={"class_type":"SamplerCustom","inputs":{"model":["6",0],"add_noise":True,"noise_seed":seed,"cfg":3.0,"positive":["30",0],"negative":["30",1],"sampler":["9",0],"sigmas":["8",0],"latent_image":["30",2]}}
        g["14"]={"class_type":"LTXVCropGuides","inputs":{"positive":["30",0],"negative":["30",1],"latent":["10",0]}}
        g["11"]={"class_type":"VAEDecode","inputs":{"samples":["14",2],"vae":["1",2]}}
    else:
        g["5"]={"class_type":"LTXVConditioning","inputs":{"positive":["3",0],"negative":["4",0],"frame_rate":25}}
        g["8"]["inputs"]["latent"]=["7",0]
        g["10"]={"class_type":"SamplerCustom","inputs":{"model":["6",0],"add_noise":True,"noise_seed":seed,"cfg":3.0,"positive":["5",0],"negative":["5",1],"sampler":["9",0],"sigmas":["8",0],"latent_image":["7",0]}}
        g["11"]={"class_type":"VAEDecode","inputs":{"samples":["10",0],"vae":["1",2]}}

    data = json.dumps({"prompt":g,"client_id":"webapp"}).encode("utf-8")
    req = urllib.request.Request(COMFY+"/prompt", data=data, headers={"Content-Type":"application/json"})
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception:
        return None
    job_id = resp.get("prompt_id")
    if not job_id: return None
    estudio = os.path.join(COMFY_OUT, "estudio_web")
    for _ in range(300):
        time.sleep(2)
        try:
            h = json.loads(urllib.request.urlopen(COMFY+f"/history/{job_id}", timeout=10).read())
        except Exception:
            continue
        if job_id in h:
            st = h[job_id].get("status",{})
            if st.get("status_str")=="error": return None
            if st.get("completed"):
                time.sleep(0.4)
                mp4s = [os.path.join(estudio,f) for f in os.listdir(estudio) if f.endswith(".mp4")]
                if not mp4s: return None
                shutil.copy(max(mp4s, key=os.path.getmtime), out_file)
                return out_file
    return None

# ---------------- mux: pega voz al visual SIN cortar la voz ----------------
def mux_av(visual, voz_mp3, out_file):
    """Une video+voz. El video se CONGELA en su ultimo frame si es mas corto que la
    voz (tpad), y se recorta a la voz si es mas largo. La voz SIEMPRE se oye completa."""
    ok, err = run(["ffmpeg","-y","-i",visual,"-i",voz_mp3,
                   "-filter_complex","[0:v]tpad=stop_mode=clone:stop_duration=600[v]",
                   "-map","[v]","-map","1:a","-shortest",
                   "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
                   "-c:a","aac","-b:a","192k",out_file])
    return out_file if ok else None

# ---------------- export final con formato + subtitulos quemados ----------------
def export_final(combinado, ass, W, H, out_file, encajar):
    """Exporta al formato WxH. Si 'encajar' (video no es WxH, p.ej. LTX 768x512):
    rellena con fondo difuminado. Quema los subtitulos karaoke (.ass, tamano real)."""
    sub = "subtitles=subs.ass"     # el estilo/tamano ya va dentro del .ass
    sal_d = os.path.dirname(ass)
    old = os.getcwd(); os.chdir(sal_d)
    try:
        if encajar:
            fc = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=22[bg];"
                  f"[0:v]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,{sub}[v]")
        else:
            fc = f"[0:v]{sub}[v]"
        ok, err = run(["ffmpeg","-y","-i",os.path.basename(combinado),"-filter_complex",fc,
                       "-map","[v]","-map","0:a?","-r",str(FPS),
                       "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
                       "-c:a","aac","-b:a","192k",os.path.basename(out_file)])
    finally:
        os.chdir(old)
    return out_file if ok else (None if not ok else out_file)

# ---------------- pipeline completo ----------------
def producir(job, texto, voz, imagenes, formato):
    try:
        W, H = FORMATOS.get(formato, FORMATOS["vertical"])
        imagenes = [p for p in (imagenes or []) if p and os.path.exists(p)]
        pdir = os.path.join(PROYECTOS, "reel_" + job[:8])
        sal_d = os.path.join(pdir,"salida"); clips_d = os.path.join(pdir,"clips")
        os.makedirs(sal_d, exist_ok=True); os.makedirs(clips_d, exist_ok=True)

        # ---- VOZ (todo el parrafo, una sola narracion continua) ----
        log(job, "Generando la voz de TODO el texto...")
        voz_mp3 = os.path.join(sal_d, "voz.mp3")
        txtf = os.path.join(sal_d, "texto.txt")
        open(txtf,"w",encoding="utf-8").write(texto)
        subprocess.run([PY,"-m","edge_tts","-f",txtf,"-v",voz,"--write-media",voz_mp3], capture_output=True)
        vdur = ffprobe_dur(voz_mp3)
        if vdur <= 0:
            JOBS[job]["estado"]="error"; JOBS[job]["error"]="No se pudo generar la voz."; return
        log(job, f"Voz lista: {vdur:.1f}s. El video durara lo mismo (nada se corta).")

        combinado = os.path.join(sal_d, "combinado.mp4")
        ass = os.path.join(sal_d, "subs.ass")

        if imagenes:
            # ===== MODO FOTOS: cada foto COBRA VIDA con IA (LTX en la GPU) =====
            # Animamos TODAS tus fotos con movimiento generado por la IA, repartiendo
            # el parrafo entre ellas. Unimos todos los clips y encimamos la voz COMPLETA
            # (nada de audio se corta). Subtitulos reel quemados al final.
            if not comfy_vivo():
                log(job,"Encendiendo ComfyUI (la 1ra vez tarda ~1 min)...")
                subprocess.Popen([r"C:\AI\ComfyUI_windows_portable\INICIAR_ComfyUI_RTX3070.bat"], shell=True)
                for _ in range(80):
                    time.sleep(3)
                    if comfy_vivo(): break

            nseg = len(dividir_parrafo(texto))
            ncli = max(nseg, len(imagenes))          # >= #fotos -> TODAS las fotos se animan
            di   = max(2.0, vdur / ncli)             # cada clip cubre su parte de la voz
            prompts = repartir_texto(texto, ncli)    # un trozo de texto guia cada foto
            JOBS[job]["total"] = ncli
            log(job, f"Motor IA: dando vida a {len(imagenes)} foto(s) en {ncli} clip(s) (~{di:.1f}s c/u)...")

            clips = []
            for i in range(ncli):
                JOBS[job]["progreso"] = i + 1
                foto = imagenes[i % len(imagenes)]
                log(job, f"Clip {i+1}/{ncli}: animando la foto {(i % len(imagenes)) + 1} en la GPU...")
                clip = os.path.join(clips_d, f"clip_{i+1:03d}.mp4")
                if generar_clip_ltx(prompts[i] or texto, math.ceil(min(di, MAX_SEG_CLIP)), foto, clip):
                    clips.append(clip)
                else:
                    log(job, f"  (Clip {i+1} no se pudo generar, lo salto)")

            if clips:
                # unir TODOS los clips animados (solo video) en uno solo
                log(job, f"Uniendo los {len(clips)} clip(s) animados...")
                visual = os.path.join(sal_d, "visual_raw.mp4")
                lista_v = os.path.join(sal_d, "lista_fotos.txt")
                with open(lista_v,"w",encoding="utf-8") as f:
                    for c in clips: f.write(f"file '{c.replace(chr(92),'/')}'\n")
                if not run(["ffmpeg","-y","-f","concat","-safe","0","-i",lista_v,
                            "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",visual])[0]:
                    JOBS[job]["estado"]="error"; JOBS[job]["error"]="Fallo al unir los clips animados."; return
                encajar = True   # LTX 768x512 -> rellenar al formato elegido con fondo difuminado
            else:
                # respaldo de emergencia: la GPU/LTX no dio ni un clip (¿ComfyUI apagado?).
                # No dejamos al user sin video: animacion rapida de respaldo.
                log(job, "La GPU no genero clips; uso un respaldo rapido para no dejarte sin video.")
                visual = os.path.join(sal_d, "visual.mp4")
                if not kenburns(imagenes, vdur, W, H, visual, job):
                    JOBS[job]["estado"]="error"; JOBS[job]["error"]="No se pudieron animar las fotos. ¿ComfyUI esta encendido?"; return
                encajar = False

            log(job, "Pegando la voz COMPLETA al video (nada se corta)...")
            if not mux_av(visual, voz_mp3, combinado):
                JOBS[job]["estado"]="error"; JOBS[job]["error"]="Fallo al unir voz y video."; return
            escribir_ass(ass, W, H, _ass_eventos(texto, vdur, 0.0))
        else:
            # ===== MODO TEXTO: clips LTX en la GPU, cada uno estirado a su voz =====
            if not comfy_vivo():
                log(job,"Encendiendo ComfyUI (la 1ra vez tarda ~1 min)...")
                subprocess.Popen([r"C:\AI\ComfyUI_windows_portable\INICIAR_ComfyUI_RTX3070.bat"], shell=True)
                for _ in range(80):
                    time.sleep(3)
                    if comfy_vivo(): break
            segmentos = dividir_parrafo(texto)
            JOBS[job]["total"] = len(segmentos)
            log(job, f"Tu idea se dividio en {len(segmentos)} clip(s). Empezando...")
            escenas=[]; ass_ev=[]; t_acc=0.0; prev_last=None
            for i, seg in enumerate(segmentos, 1):
                JOBS[job]["progreso"] = i
                vmp3 = os.path.join(sal_d, f"voz_{i}.mp3")
                segf = os.path.join(sal_d, f"seg_{i}.txt"); open(segf,"w",encoding="utf-8").write(seg)
                subprocess.run([PY,"-m","edge_tts","-f",segf,"-v",voz,"--write-media",vmp3], capture_output=True)
                sdur = ffprobe_dur(vmp3) or 4.0
                log(job, f"Clip {i}/{len(segmentos)}: generando video en la GPU...")
                clip = os.path.join(clips_d, f"clip_{i:03d}.mp4")
                if not generar_clip_ltx(seg, math.ceil(sdur), prev_last, clip):
                    log(job, f"  (Clip {i} fallo, lo salto)"); continue
                prev_last = os.path.join(sal_d, f"last_{i:03d}.png")
                run(["ffmpeg","-y","-sseof","-0.1","-i",clip,"-frames:v","1",prev_last])
                if not os.path.exists(prev_last): prev_last=None
                escena = os.path.join(sal_d, f"escena_{i:03d}.mp4")
                if not mux_av(clip, vmp3, escena):  # estira el clip a su voz, sin cortes
                    continue
                cdur = ffprobe_dur(escena) or sdur
                ass_ev += _ass_eventos(seg, cdur, t_acc)
                t_acc += cdur; escenas.append(escena)
            if not escenas:
                JOBS[job]["estado"]="error"; JOBS[job]["error"]="No se genero ningun clip."; return
            log(job,"Uniendo todos los clips...")
            lista = os.path.join(sal_d,"lista.txt")
            with open(lista,"w",encoding="utf-8") as f:
                for e in escenas: f.write(f"file '{e.replace(chr(92),'/')}'\n")
            if not run(["ffmpeg","-y","-f","concat","-safe","0","-i",lista,
                        "-c:v","libx264","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",combinado])[0]:
                JOBS[job]["estado"]="error"; JOBS[job]["error"]="Fallo al unir clips."; return
            escribir_ass(ass, W, H, ass_ev)
            encajar = True   # LTX 768x512 -> rellenar con fondo difuminado

        # ---- EXPORT FINAL ----
        log(job, f"Exportando en {formato} ({W}x{H}) con subtitulos...")
        final = os.path.join(sal_d, "REEL_FINAL.mp4")
        if not export_final(combinado, ass, W, H, final, encajar) or not os.path.exists(final):
            JOBS[job]["estado"]="error"; JOBS[job]["error"]="Fallo el export final."; return

        # ---- GUARDAR ORGANIZADO EN EL ESCRITORIO ----
        carpeta = carpeta_proyecto(texto)
        nombre_final = f"VIDEO_{slug(texto)}_{formato}.mp4"
        dest = os.path.join(carpeta, nombre_final)
        shutil.copy(final, dest)
        shutil.copy(ass, os.path.join(carpeta, "subtitulos.ass"))
        shutil.copy(voz_mp3, os.path.join(carpeta, "voz.mp3"))
        if imagenes:
            idir = os.path.join(carpeta, "fotos_usadas"); os.makedirs(idir, exist_ok=True)
            for k, p in enumerate(imagenes, 1):
                shutil.copy(p, os.path.join(idir, f"{k:02d}_{os.path.basename(p)}"))
        open(os.path.join(carpeta,"texto.txt"),"w",encoding="utf-8").write(texto)

        JOBS[job]["video"] = final
        JOBS[job]["carpeta"] = carpeta
        JOBS[job]["dest"] = dest
        JOBS[job]["estado"]="listo"
        log(job, f"LISTO! Guardado organizado en: {os.path.relpath(carpeta, DESKTOP)}\\")
        log(job, f"Archivo: {nombre_final}")
    except Exception as ex:
        import traceback; traceback.print_exc()
        JOBS[job]["estado"]="error"; JOBS[job]["error"]=str(ex)
        log(job, f"ERROR: {ex}")

# ---------------- rutas ----------------
@app.route("/")
def index():
    return send_file(os.path.join(os.path.dirname(__file__),"templates","index.html"))

@app.route("/api/generate", methods=["POST"])
def api_generate():
    texto = request.form.get("texto","").strip()
    voz = request.form.get("voz","es-MX-JorgeNeural")
    formato = request.form.get("formato","vertical")
    if formato not in FORMATOS: formato = "vertical"
    if not texto:
        return jsonify({"error":"Escribe tu idea primero."}), 400
    files = request.files.getlist("imagenes") + request.files.getlist("imagen")
    imagenes = []
    if files:
        updir = os.path.join(PROYECTOS,"_uploads"); os.makedirs(updir, exist_ok=True)
        for f in files:
            if not f or not f.filename: continue
            dest = os.path.join(updir, f"{uuid.uuid4().hex}_{f.filename}")
            f.save(dest); imagenes.append(dest)
    job = uuid.uuid4().hex
    JOBS[job] = {"estado":"trabajando","progreso":0,"total":0,"mensajes":[],
                 "video":None,"error":None,"carpeta":None}
    threading.Thread(target=producir, args=(job,texto,voz,imagenes,formato), daemon=True).start()
    n = 1 if imagenes else len(dividir_parrafo(texto))
    return jsonify({"job":job, "clips_estimados":n, "modo": ("fotos" if imagenes else "texto")})

@app.route("/api/status/<job>")
def api_status(job):
    j = JOBS.get(job)
    if not j: return jsonify({"error":"no existe"}),404
    return jsonify({"estado":j["estado"],"progreso":j["progreso"],"total":j["total"],
                    "mensajes":j["mensajes"],"error":j["error"],
                    "carpeta":j.get("carpeta"),
                    "tiene_video": j["video"] is not None})

@app.route("/api/video/<job>")
def api_video(job):
    j = JOBS.get(job)
    if not j or not j["video"]: return "no listo",404
    return send_file(j["video"], mimetype="video/mp4")

@app.route("/api/abrir/<job>", methods=["POST"])
def api_abrir(job):
    j = JOBS.get(job)
    if not j or not j.get("carpeta"): return jsonify({"ok":False}),404
    try:
        os.startfile(j["carpeta"])   # abre la carpeta en el Explorador
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}),500

@app.route("/api/estimar", methods=["POST"])
def api_estimar():
    data = request.get_json(force=True, silent=True) or {}
    texto = data.get("texto","")
    con_fotos = bool(data.get("con_fotos"))
    chars = len(texto.strip())
    seg = max(2, round(chars / 14.0))            # ~14 caracteres/seg en es-MX
    clips = 1 if con_fotos else len(dividir_parrafo(texto))
    return jsonify({"clips": clips, "segundos": seg, "con_fotos": con_fotos})

if __name__ == "__main__":
    os.makedirs(SALIDA_RAIZ, exist_ok=True)
    print("="*55)
    print("  ESTUDIO DE VIDEO IA v2  ->  http://127.0.0.1:5000")
    print("  Salida organizada en:", SALIDA_RAIZ)
    print("="*55)
    app.run(host="127.0.0.1", port=5000, threaded=True)

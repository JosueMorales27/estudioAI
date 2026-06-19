# -*- coding: utf-8 -*-
"""
ESTUDIO DE VIDEO IA  -  App web local  (v4 - constructor de ESCENAS)
100% local / open source. NO usa Claude ni APIs de pago.

NOVEDADES v4:
  - CONSTRUCTOR DE ESCENAS: armas tu reel escena por escena, ilimitadas.
    Cada escena tiene:
      * IMAGEN  -> la SUBES tu, o la GENERAS desde texto (SDXL en tu GPU).
      * MOVIMIENTO (motion prompt) -> que hace la imagen en el video
                    (ej: "man turning into bones after he falls") via LTX-Video.
      * NARRACION (opcional) -> lo que se ESCUCHA en esa escena (voz + karaoke).
  - TEXTO->IMAGEN con SDXL: prompteas palabras y sale la imagen; la previsualizas
    antes de animarla.
  - REPARTO DE NARRACION: si dejas escenas sin narracion, el programa reparte tu
    texto global entre ellas por frases. Cada clip se cronometra a SU narracion:
    el audio y los subtitulos NUNCA se cortan.
  - LIP-SYNC (talk): una escena puede hacer que el ROSTRO de la imagen MUEVA LOS
    LABIOS con el audio (SadTalker). Si aun no esta instalado, cae a movimiento.
  - Voz edge-tts + subtitulos KARAOKE (palabra x palabra) quemados.
  - Une todo con ffmpeg y exporta 9:16 / 1:1 / 16:9. Resultado organizado en:
    Escritorio\\Estudio de Video IA\\<proyecto>\\
"""
import os, re, json, time, uuid, threading, subprocess, math, shutil, urllib.request
from flask import Flask, request, jsonify, send_file

# ---------------- Config ----------------
COMFY      = "http://127.0.0.1:8188"
COMFY_ROOT = r"C:\AI\ComfyUI_windows_portable\ComfyUI"
COMFY_OUT  = os.path.join(COMFY_ROOT, "output")
COMFY_IN   = os.path.join(COMFY_ROOT, "input")
COMFY_BAT  = r"C:\AI\ComfyUI_windows_portable\INICIAR_ComfyUI_RTX3070.bat"
CKPT_DIR   = os.path.join(COMFY_ROOT, "models", "checkpoints")
PROYECTOS  = r"C:\AI\VideoStudio\proyectos"
DESKTOP    = os.path.join(os.path.expanduser("~"), "Desktop")
SALIDA_RAIZ= os.path.join(DESKTOP, "Estudio de Video IA")
FONT_SRC   = r"C:\Windows\Fonts\arialbd.ttf"

# --- Modelos ---
CKPT       = "ltx-video-2b-v0.9.5.safetensors"      # video (LTX img2vid / txt2vid)
T5         = "t5xxl_fp8_e4m3fn_scaled.safetensors"   # text encoder de LTX
SDXL_CKPT  = "sd_xl_base_1.0.safetensors"            # texto -> imagen (descarga aparte)

FPS = 30
CHARS_POR_CLIP = 95
MAX_SEG_CLIP   = 7         # tope LTX por VRAM 8GB

FORMATOS = {
    "vertical":   (1080, 1920),
    "cuadrado":   (1080, 1080),
    "horizontal": (1920, 1080),
}
# dimensiones nativas SDXL (~1MP) segun orientacion del reel
SDXL_DIMS = {"vertical": (832, 1216), "cuadrado": (1024, 1024), "horizontal": (1216, 832)}

PY = __import__("sys").executable
NEG_IMG = ("blurry, low quality, lowres, deformed, bad anatomy, disfigured, "
           "watermark, text, signature, jpeg artifacts, ugly, extra limbs, cropped")
NEG_VID = "blurry, low quality, distorted, deformed, static, watermark, text, jpeg artifacts"

app = Flask(__name__)
JOBS = {}
_NODE_CACHE = None   # cache de /object_info (que nodos tiene ComfyUI)

# ---------------- utilidades base ----------------
def log(job, msg):
    if job in JOBS: JOBS[job]["mensajes"].append(msg)
    print(f"[{(job or '------')[:6]}] {msg}", flush=True)

def comfy_vivo():
    try:
        urllib.request.urlopen(COMFY + "/system_stats", timeout=3); return True
    except Exception:
        return False

def asegurar_comfy(job=None):
    """Enciende ComfyUI si esta apagado y espera a que responda."""
    if comfy_vivo(): return True
    if job: log(job, "Encendiendo ComfyUI (la 1ra vez tarda ~1 min)...")
    try:
        subprocess.Popen([COMFY_BAT], shell=True)
    except Exception as e:
        if job: log(job, f"  No pude lanzar ComfyUI: {e}")
        return False
    for _ in range(90):
        time.sleep(3)
        if comfy_vivo(): return True
    return False

def comfy_tiene_nodo(*nombres):
    """True si ComfyUI tiene CUALQUIERA de esas clases de nodo instaladas."""
    global _NODE_CACHE
    if _NODE_CACHE is None:
        try:
            _NODE_CACHE = json.loads(urllib.request.urlopen(COMFY + "/object_info", timeout=10).read())
        except Exception:
            return False
    return any(n in _NODE_CACHE for n in nombres)

def sdxl_listo():
    return os.path.exists(os.path.join(CKPT_DIR, SDXL_CKPT))

def ffprobe_dur(path):
    try:
        out = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                              "-of","csv=p=0",path], capture_output=True, text=True)
        return float(out.stdout.strip())
    except Exception:
        return 0.0

def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode == 0, (p.stderr or "")

def slug(texto, n=5):
    palabras = re.findall(r"[A-Za-z0-9ÁÉÍÓÚáéíóúÑñ]+", texto or "")[:n]
    s = "_".join(palabras).lower() or "video"
    return s[:40]

def carpeta_proyecto(texto):
    os.makedirs(SALIDA_RAIZ, exist_ok=True)
    nombre = time.strftime("%Y-%m-%d_%H%M") + "_" + slug(texto)
    dest = os.path.join(SALIDA_RAIZ, nombre)
    i = 2
    while os.path.exists(dest):
        dest = os.path.join(SALIDA_RAIZ, f"{nombre}_{i}"); i += 1
    os.makedirs(dest, exist_ok=True)
    return dest

# ---------------- division / reparto de texto ----------------
def dividir_parrafo(texto, limite=CHARS_POR_CLIP):
    texto = (texto or "").strip()
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
                        palabras = s.split(); buf = ""
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
    return segmentos or ([texto[:limite]] if texto else [])

def repartir_texto(texto, n):
    """Parte el texto en n trozos balanceados por palabras (nunca vacio)."""
    texto = (texto or "").strip()
    if n <= 1: return [texto]
    words = texto.split()
    if len(words) < n:
        return [texto for _ in range(n)]
    per = len(words) / n
    chunks = []
    for i in range(n):
        a = int(round(i * per)); b = int(round((i + 1) * per))
        chunks.append(" ".join(words[a:b]).strip() or texto)
    return chunks

def repartir_frases(texto, n):
    """Reparte el texto en n grupos respetando frases (mas natural para la voz).
    Si hay menos frases que n, cae a reparto por palabras."""
    texto = (texto or "").strip()
    if n <= 1: return [texto]
    frases = [f.strip() for f in re.split(r'(?<=[\.\!\?\n])\s+', texto) if f.strip()]
    if len(frases) < n:
        return repartir_texto(texto, n)
    total = sum(len(f) for f in frases) or 1
    objetivo = total / n
    grupos, buf, cur = [], [], 0
    for i, f in enumerate(frases):
        buf.append(f); cur += len(f)
        restan_frases = len(frases) - (i + 1)
        restan_grupos = n - len(grupos) - 1
        if cur >= objetivo and restan_grupos > 0 and restan_frases >= restan_grupos:
            grupos.append(" ".join(buf)); buf = []; cur = 0
    if buf: grupos.append(" ".join(buf))
    while len(grupos) < n: grupos.append("")
    return grupos[:n]

# ---------------- subtitulos KARAOKE (ASS, palabra x palabra) ----------------
def _ass_ts(seg):
    if seg < 0: seg = 0
    h = int(seg // 3600); m = int((seg % 3600) // 60); s = int(seg % 60)
    cs = int(round((seg - int(seg)) * 100))
    if cs == 100: s += 1; cs = 0
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def _ass_safe(t):
    return t.replace("{", "(").replace("}", ")").replace("\n", " ").strip()

def _ass_header(W, H):
    base = min(W, H)
    fs   = max(18, int(base * 0.045))
    mv   = int(H * 0.11)
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

def trocear_para_subs(texto, max_chars=30):
    frases = re.split(r'(?<=[\.\!\?])\s+', (texto or "").strip())
    chunks = []
    for fr in frases:
        words = fr.split(); buf = ""
        for w in words:
            if len(buf) + len(w) + 1 <= max_chars:
                buf = (buf + " " + w).strip()
            else:
                if buf: chunks.append(buf)
                buf = w
        if buf: chunks.append(buf)
    return [c for c in chunks if c]

def _ass_eventos(texto, dur_total, t0=0.0):
    chunks = trocear_para_subs(texto, max_chars=30)
    if not chunks: return []
    total_chars = sum(len(c) for c in chunks) or 1
    eventos = []; t = t0
    for c in chunks:
        d = max(0.9, dur_total * (len(c) / total_chars))
        words = c.split()
        wchars = sum(len(w) for w in words) or 1
        wt = t
        for k, w in enumerate(words):
            wd = max(0.14, d * (len(w) / wchars))
            fin = t + d if k == len(words) - 1 else min(t + d, wt + wd)
            visible = _ass_safe(" ".join(words[:k + 1]))
            eventos.append(f"Dialogue: 0,{_ass_ts(wt)},{_ass_ts(fin)},Sub,,0,0,0,,{visible}")
            wt = fin
        t += d
    return eventos

def escribir_ass(path, W, H, eventos):
    with open(path, "w", encoding="utf-8") as f:
        f.write(_ass_header(W, H))
        f.write("\n".join(eventos) + "\n")

# ---------------- ComfyUI: motor generico ----------------
def comfy_run(graph, subdir, exts, out_file, timeout=300, job=None, client="webapp"):
    """Encola un grafo en ComfyUI, espera, y copia el archivo nuevo (de
    COMFY_OUT/subdir con extension en exts) a out_file. Devuelve out_file o None."""
    data = json.dumps({"prompt": graph, "client_id": client}).encode("utf-8")
    req = urllib.request.Request(COMFY + "/prompt", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        if job: log(job, f"  (ComfyUI no acepto el trabajo: {e})")
        return None
    pid = resp.get("prompt_id")
    if not pid: return None
    carpeta = os.path.join(COMFY_OUT, subdir)
    for _ in range(timeout // 2):
        time.sleep(2)
        try:
            h = json.loads(urllib.request.urlopen(COMFY + f"/history/{pid}", timeout=10).read())
        except Exception:
            continue
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                if job: log(job, "  (ComfyUI reporto error en el render)")
                return None
            if st.get("completed"):
                time.sleep(0.4)
                if not os.path.isdir(carpeta): return None
                arch = [os.path.join(carpeta, f) for f in os.listdir(carpeta)
                        if f.lower().endswith(tuple(exts))]
                if not arch: return None
                shutil.copy(max(arch, key=os.path.getmtime), out_file)
                return out_file
    return None

# ---------------- TEXTO -> IMAGEN (SDXL) ----------------
def generar_imagen_sdxl(prompt, formato, out_png, job=None, seed=None):
    """Genera una imagen desde texto con SDXL. Devuelve out_png o None."""
    if not sdxl_listo():
        if job: log(job, "  (SDXL aun no esta descargado)")
        return None
    sw, sh = SDXL_DIMS.get(formato, SDXL_DIMS["vertical"])
    seed = seed if seed is not None else (uuid.uuid4().int % 2147483000)
    g = {
        "1": {"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":SDXL_CKPT}},
        "2": {"class_type":"CLIPTextEncode","inputs":{"text":prompt,"clip":["1",1]}},
        "3": {"class_type":"CLIPTextEncode","inputs":{"text":NEG_IMG,"clip":["1",1]}},
        "4": {"class_type":"EmptyLatentImage","inputs":{"width":sw,"height":sh,"batch_size":1}},
        "5": {"class_type":"KSampler","inputs":{"seed":seed,"steps":28,"cfg":7.0,
              "sampler_name":"dpmpp_2m","scheduler":"karras","denoise":1.0,
              "model":["1",0],"positive":["2",0],"negative":["3",0],"latent_image":["4",0]}},
        "6": {"class_type":"VAEDecode","inputs":{"samples":["5",0],"vae":["1",2]}},
        "7": {"class_type":"SaveImage","inputs":{"filename_prefix":"estudio_img/img","images":["6",0]}},
    }
    return comfy_run(g, "estudio_img", (".png",), out_png, timeout=180, job=job)

# ---------------- IMAGEN/TEXTO -> VIDEO (LTX) ----------------
def _largo_auto(segundos):
    segundos = min(MAX_SEG_CLIP, max(2, segundos or 4))
    return max(9, int(math.floor((segundos * 25) / 8) * 8 + 1))

def generar_clip_ltx(prompt, segundos, imagen_guia, out_file, job=None):
    """Clip LTX. imagen_guia (opcional) ancla el 1er frame (img2vid)."""
    length = _largo_auto(segundos)
    seed = uuid.uuid4().int % 2147483000
    g = {
        "1": {"class_type":"CheckpointLoaderSimple","inputs":{"ckpt_name":CKPT}},
        "2": {"class_type":"CLIPLoader","inputs":{"clip_name":T5,"type":"ltxv"}},
        "3": {"class_type":"CLIPTextEncode","inputs":{"text":prompt,"clip":["2",0]}},
        "4": {"class_type":"CLIPTextEncode","inputs":{"text":NEG_VID,"clip":["2",0]}},
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
    return comfy_run(g, "estudio_web", (".mp4",), out_file, timeout=600, job=job)

# ---------------- LIP-SYNC (rostro habla) -- entorno AISLADO en C:\AI\lipsync ----
LIPSYNC_DIR = r"C:\AI\lipsync"
LIPSYNC_PY  = os.path.join(LIPSYNC_DIR, "python", "python.exe")
LIPSYNC_CFG = os.path.join(LIPSYNC_DIR, "engine.json")   # {"engine":"sadtalker"|"wav2lip"}

def lipsync_engine():
    """Motor de lip-sync instalado en el entorno aislado, o None."""
    try:
        if os.path.exists(LIPSYNC_CFG):
            return (json.load(open(LIPSYNC_CFG, encoding="utf-8")).get("engine") or None)
    except Exception:
        pass
    return None

def lipsync_disponible():
    return bool(lipsync_engine()) and os.path.exists(LIPSYNC_PY)

def _mp3_a_wav(mp3, wav):
    return run(["ffmpeg","-y","-i",mp3,"-ar","16000","-ac","1",wav])[0]

def _buscar_mp4(carpeta):
    res = []
    for root,_,files in os.walk(carpeta):
        for f in files:
            if f.lower().endswith(".mp4"): res.append(os.path.join(root,f))
    return res

def _sadtalker_run(imagen, wav, out_file, job=None):
    sad = os.path.join(LIPSYNC_DIR, "SadTalker")
    resdir = os.path.join(LIPSYNC_DIR, "_out", uuid.uuid4().hex)
    os.makedirs(resdir, exist_ok=True)
    # 512 + realce GFPGAN = rostro nitido (no borroso). --still = sin saltos de cabeza.
    cmd = [LIPSYNC_PY, "inference.py", "--driven_audio", wav, "--source_image", imagen,
           "--result_dir", resdir, "--still", "--preprocess", "full", "--size", "512",
           "--enhancer", "gfpgan"]
    try:
        p = subprocess.run(cmd, cwd=sad, capture_output=True, text=True, timeout=1200)
    except Exception as e:
        if job: log(job, f"  (SadTalker no corrio: {e})"); return None
    mp4s = _buscar_mp4(resdir)
    if not mp4s:
        if job: log(job, "  (SadTalker sin salida) " + (p.stderr or "")[-200:])
        return None
    shutil.copy(max(mp4s, key=os.path.getmtime), out_file)
    return out_file

def _wav2lip_run(imagen, wav, out_file, job=None):
    """Wav2Lip necesita un video/imagen + audio. Corre el inference del entorno aislado."""
    w2l = os.path.join(LIPSYNC_DIR, "Wav2Lip")
    ckpt = os.path.join(w2l, "checkpoints", "wav2lip_gan.pth")
    if not os.path.exists(ckpt): return None
    try:
        p = subprocess.run([LIPSYNC_PY, "inference.py", "--checkpoint_path", ckpt,
                            "--face", imagen, "--audio", wav, "--outfile", out_file],
                           cwd=w2l, capture_output=True, text=True, timeout=1200)
    except Exception as e:
        if job: log(job, f"  (Wav2Lip no corrio: {e})"); return None
    if not os.path.exists(out_file):
        if job: log(job, "  (Wav2Lip sin salida) " + (p.stderr or "")[-200:])
        return None
    return out_file

def generar_talking_head(imagen, voz_mp3, out_file, job=None):
    """Hace que el ROSTRO de 'imagen' mueva los labios con 'voz_mp3'.
    Usa el motor del entorno AISLADO (SadTalker o Wav2Lip). El mp4 sale CON audio.
    Devuelve out_file o None (entonces el pipeline cae a movimiento normal)."""
    eng = lipsync_engine()
    if not eng or not os.path.exists(LIPSYNC_PY):
        return None
    wav = out_file + ".wav"
    if not _mp3_a_wav(voz_mp3, wav):
        return None
    try:
        if eng == "sadtalker": return _sadtalker_run(imagen, wav, out_file, job)
        if eng == "wav2lip":   return _wav2lip_run(imagen, wav, out_file, job)
    except Exception as e:
        if job: log(job, f"  (lip-sync error: {e})")
    return None

# ---------------- Ken Burns (respaldo si la GPU esta apagada) ----------------
def _zoompan_para(idx, di, W, H):
    frames = max(1, int(round(di * FPS))); f = frames
    base = f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},setsar=1"
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    ease  = f"(1-cos(PI*on/{f}))/2"; easeI = f"(1+cos(PI*on/{f}))/2"
    modo = idx % 6
    if modo == 0:   z, x, y = "min(zoom+0.0015,1.30)", cx, cy
    elif modo == 1: z, x, y = "1.30", f"(iw-iw/zoom)*{ease}", cy
    elif modo == 2: z, x, y = "1.30", f"(iw-iw/zoom)*{easeI}", cy
    elif modo == 3: z, x, y = "1.30", cx, f"(ih-ih/zoom)*{ease}"
    elif modo == 4: z, x, y = "min(zoom+0.0012,1.35)", f"(iw-iw/zoom)*{ease}", f"(ih-ih/zoom)*{ease}"
    else:           z, x, y = "if(eq(on,0),1.30,max(zoom-0.0015,1.0))", cx, cy
    zp = (f"zoompan=z='{z}':x='{x}':y='{y}':d={f}:s={W}x{H}:fps={FPS}")
    return f"{base},{zp},format=yuv420p"

def kenburns(imagenes, dur_total, W, H, out_file, job=None):
    imgs = [p for p in imagenes if p and os.path.exists(p)]
    if not imgs: return None
    n = len(imgs)
    if n == 1:
        fc = "[0:v]" + _zoompan_para(0, dur_total, W, H) + "[v]"
        ok, err = run(["ffmpeg","-y","-i",imgs[0],"-filter_complex",fc,"-map","[v]","-r",str(FPS),
                       "-t",f"{dur_total:.3f}","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",out_file])
        return out_file if ok else None
    tr = max(0.5, min(1.0, dur_total / (n * 3.0)))
    di = (dur_total + (n - 1) * tr) / n; di = max(di, tr + 0.6)
    transiciones = ["fade","smoothleft","smoothright","wipeleft","circlecrop","fadeblack","slideup"]
    cmd = ["ffmpeg","-y"]
    for p in imgs: cmd += ["-i",p]
    parts = [f"[{i}:v]{_zoompan_para(i, di, W, H)}[v{i}]" for i in range(n)]
    prev = "v0"; offset = di - tr
    for i in range(1, n):
        outl = f"x{i}" if i < n - 1 else "v"
        trn = transiciones[(i - 1) % len(transiciones)]
        parts.append(f"[{prev}][v{i}]xfade=transition={trn}:duration={tr:.3f}:offset={offset:.3f}[{outl}]")
        prev = outl; offset += di - tr
    fc = ";".join(parts)
    ok, err = run(cmd + ["-filter_complex",fc,"-map","[v]","-r",str(FPS),
                          "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",out_file])
    return out_file if ok else None

# ---------------- mux / export ----------------
def mux_av(visual, voz_mp3, out_file):
    """Pega voz al visual. El video se congela en su ultimo frame si es mas corto
    que la voz; la voz se oye COMPLETA."""
    ok, err = run(["ffmpeg","-y","-i",visual,"-i",voz_mp3,
                   "-filter_complex","[0:v]tpad=stop_mode=clone:stop_duration=600[v]",
                   "-map","[v]","-map","1:a","-shortest",
                   "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
                   "-c:a","aac","-b:a","192k",out_file])
    return out_file if ok else None

def export_final(combinado, ass, W, H, out_file, encajar):
    sub = "subtitles=subs.ass"
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
    return out_file if ok else None

def voz_de(texto, voz, out_mp3):
    """Genera voz con edge-tts. Devuelve duracion (s) o 0."""
    txtf = out_mp3 + ".txt"
    open(txtf, "w", encoding="utf-8").write(texto)
    subprocess.run([PY,"-m","edge_tts","-f",txtf,"-v",voz,"--write-media",out_mp3], capture_output=True)
    return ffprobe_dur(out_mp3)

# ---------------- PIPELINE por ESCENAS ----------------
def producir_escenas(job, cfg, uploads):
    try:
        formato = cfg.get("formato","vertical")
        if formato not in FORMATOS: formato = "vertical"
        W, H = FORMATOS[formato]
        voz = cfg.get("voz","es-MX-JorgeNeural")
        escenas = cfg.get("scenes") or []
        global_narr = (cfg.get("global_narration") or "").strip()
        if not escenas:
            JOBS[job]["estado"]="error"; JOBS[job]["error"]="No hay escenas que generar."; return

        pdir = os.path.join(PROYECTOS, "reel_" + job[:8])
        sal_d = os.path.join(pdir,"salida"); clips_d = os.path.join(pdir,"clips")
        os.makedirs(sal_d, exist_ok=True); os.makedirs(clips_d, exist_ok=True)

        # ---- reparto de narracion: escenas sin texto se llenan del texto global ----
        narrs = [ (s.get("narration") or "").strip() for s in escenas ]
        vacias = [i for i,t in enumerate(narrs) if not t]
        if global_narr and vacias:
            partes = repartir_frases(global_narr, len(vacias))
            for k, i in enumerate(vacias):
                narrs[i] = partes[k] if k < len(partes) else ""

        n = len(escenas)
        JOBS[job]["total"] = n
        necesita_gpu = any(s.get("image_mode")=="generate" or s.get("anim_mode") in ("motion","talk") for s in escenas)
        if necesita_gpu and not asegurar_comfy(job):
            log(job, "ComfyUI no encendio; usare respaldos donde pueda.")

        texto_completo = global_narr or " ".join([t for t in narrs if t])
        escenas_mp4 = []      # (mp4_con_audio_o_no, dur, tiene_audio)
        ass_ev = []; t_acc = 0.0
        imgs_usadas = []

        for i, s in enumerate(escenas, 1):
            JOBS[job]["progreso"] = i
            modo_img = s.get("image_mode","upload")
            anim     = s.get("anim_mode","motion")
            img_prompt = (s.get("image_prompt") or "").strip()
            motion     = (s.get("motion_prompt") or "").strip()
            narr       = narrs[i-1]

            # ---- 1) resolver la IMAGEN de la escena ----
            img_path = None
            if modo_img == "generate" and img_prompt:
                log(job, f"Escena {i}/{n}: generando imagen desde texto (SDXL)...")
                img_path = os.path.join(sal_d, f"img_{i:03d}.png")
                if not generar_imagen_sdxl(img_prompt, formato, img_path, job):
                    log(job, f"  (No se pudo generar la imagen de la escena {i}; la salto)")
                    img_path = None
            else:
                ui = s.get("upload_index")
                if isinstance(ui, int) and 0 <= ui < len(uploads):
                    img_path = uploads[ui]
            if not img_path or not os.path.exists(img_path):
                log(job, f"Escena {i}: sin imagen valida, la salto.")
                continue
            imgs_usadas.append(img_path)

            # ---- 2) VOZ de la escena (si tiene narracion) ----
            vmp3 = None; dur = 0.0
            if narr:
                log(job, f"Escena {i}/{n}: generando voz...")
                vmp3 = os.path.join(sal_d, f"voz_{i:03d}.mp3")
                dur = voz_de(narr, voz, vmp3)
                if dur <= 0: vmp3 = None
            if dur <= 0:
                dur = float(s.get("dur_silenciosa") or 4.0)   # escena sin voz

            # ---- 3) ANIMAR la imagen ----
            escena_mp4 = os.path.join(clips_d, f"escena_{i:03d}.mp4")
            tiene_audio = False

            if anim == "talk" and vmp3:
                log(job, f"Escena {i}/{n}: lip-sync (el rostro habla)...")
                th = generar_talking_head(img_path, vmp3, escena_mp4, job)
                if th:
                    tiene_audio = True
                else:
                    log(job, "  (lip-sync no disponible aun; uso movimiento normal)")
                    anim = "motion"

            if not tiene_audio:
                # MOVIMIENTO con LTX (o Ken Burns de respaldo) + voz encimada
                clip = os.path.join(clips_d, f"clip_{i:03d}.mp4")
                guia = motion or narr or texto_completo
                hecho = generar_clip_ltx(guia, math.ceil(min(dur, MAX_SEG_CLIP)), img_path, clip, job) if comfy_vivo() else None
                if not hecho:
                    if comfy_vivo(): log(job, f"  (LTX fallo en escena {i}; uso animacion de respaldo)")
                    clip2 = os.path.join(clips_d, f"kb_{i:03d}.mp4")
                    hecho = kenburns([img_path], dur, W, H, clip2, job)
                    clip = clip2 if hecho else None
                if not hecho:
                    log(job, f"  (No pude animar la escena {i}; la salto)"); continue
                if vmp3:
                    if not mux_av(clip, vmp3, escena_mp4): escena_mp4 = clip
                    else: tiene_audio = True
                else:
                    escena_mp4 = clip

            durf = ffprobe_dur(escena_mp4) or dur
            if narr:
                ass_ev += _ass_eventos(narr, durf, t_acc)
            t_acc += durf
            escenas_mp4.append((escena_mp4, tiene_audio))

        if not escenas_mp4:
            JOBS[job]["estado"]="error"; JOBS[job]["error"]="No se genero ninguna escena."; return

        # ---- unir todas las escenas ----
        log(job, f"Uniendo {len(escenas_mp4)} escena(s)...")
        combinado = os.path.join(sal_d, "combinado.mp4")
        lista = os.path.join(sal_d, "lista.txt")
        # normalizamos: aseguramos pista de audio en cada escena (silencio si no tiene)
        norm = []
        for k,(mp4, has_a) in enumerate(escenas_mp4):
            nm = os.path.join(clips_d, f"norm_{k:03d}.mp4")
            if has_a:
                norm.append(mp4); continue
            ok,_ = run(["ffmpeg","-y","-f","lavfi","-i","anullsrc=channel_layout=stereo:sample_rate=48000",
                        "-i",mp4,"-shortest","-c:v","copy","-c:a","aac","-b:a","192k",nm])
            norm.append(nm if ok else mp4)
        with open(lista,"w",encoding="utf-8") as f:
            for c in norm: f.write(f"file '{c.replace(chr(92),'/')}'\n")
        if not run(["ffmpeg","-y","-f","concat","-safe","0","-i",lista,
                    "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
                    "-c:a","aac","-b:a","192k",combinado])[0]:
            JOBS[job]["estado"]="error"; JOBS[job]["error"]="Fallo al unir las escenas."; return

        # ---- subtitulos karaoke + export final ----
        ass = os.path.join(sal_d, "subs.ass")
        escribir_ass(ass, W, H, ass_ev)
        log(job, f"Exportando en {formato} ({W}x{H}) con subtitulos karaoke...")
        final = os.path.join(sal_d, "REEL_FINAL.mp4")
        if not export_final(combinado, ass, W, H, final, True) or not os.path.exists(final):
            JOBS[job]["estado"]="error"; JOBS[job]["error"]="Fallo el export final."; return

        # ---- guardar organizado en el escritorio ----
        carpeta = carpeta_proyecto(texto_completo or "reel")
        nombre_final = f"VIDEO_{slug(texto_completo or 'reel')}_{formato}.mp4"
        shutil.copy(final, os.path.join(carpeta, nombre_final))
        shutil.copy(ass, os.path.join(carpeta, "subtitulos.ass"))
        if texto_completo:
            open(os.path.join(carpeta,"texto.txt"),"w",encoding="utf-8").write(texto_completo)
        if imgs_usadas:
            idir = os.path.join(carpeta,"imagenes"); os.makedirs(idir, exist_ok=True)
            for k,p in enumerate(imgs_usadas,1):
                try: shutil.copy(p, os.path.join(idir, f"{k:02d}_{os.path.basename(p)}"))
                except Exception: pass

        JOBS[job]["video"] = final
        JOBS[job]["carpeta"] = carpeta
        JOBS[job]["estado"]="listo"
        log(job, f"LISTO! Guardado en: {os.path.relpath(carpeta, DESKTOP)}\\")
        log(job, f"Archivo: {nombre_final}")
    except Exception as ex:
        import traceback; traceback.print_exc()
        JOBS[job]["estado"]="error"; JOBS[job]["error"]=str(ex)
        log(job, f"ERROR: {ex}")

# ---------------- rutas ----------------
@app.route("/")
def index():
    return send_file(os.path.join(os.path.dirname(__file__),"templates","index.html"))

@app.route("/api/estado_motores")
def api_estado_motores():
    """Le dice a la UI que motores estan listos."""
    return jsonify({
        "comfy": comfy_vivo(),
        "sdxl": sdxl_listo(),
        "lipsync": lipsync_disponible(),
    })

@app.route("/api/genimg", methods=["POST"])
def api_genimg():
    """Genera UNA imagen desde texto (preview en vivo). Devuelve URL de la imagen."""
    data = request.get_json(force=True, silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    formato = data.get("formato","vertical")
    if not prompt: return jsonify({"error":"Escribe un prompt para la imagen."}), 400
    if not sdxl_listo(): return jsonify({"error":"SDXL todavia se esta descargando. Aguanta tantito."}), 503
    if not asegurar_comfy(): return jsonify({"error":"No pude encender ComfyUI."}), 503
    updir = os.path.join(PROYECTOS,"_previews"); os.makedirs(updir, exist_ok=True)
    iid = uuid.uuid4().hex
    out = os.path.join(updir, iid + ".png")
    if not generar_imagen_sdxl(prompt, formato, out):
        return jsonify({"error":"No se pudo generar la imagen."}), 500
    return jsonify({"id": iid, "url": f"/api/preview/{iid}"})

@app.route("/api/preview/<iid>")
def api_preview(iid):
    p = os.path.join(PROYECTOS,"_previews", re.sub(r"[^a-f0-9]","",iid) + ".png")
    if not os.path.exists(p): return "no existe",404
    return send_file(p, mimetype="image/png")

@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Recibe la config de escenas (JSON) + imagenes subidas (multipart)."""
    try:
        cfg = json.loads(request.form.get("config","{}"))
    except Exception:
        return jsonify({"error":"Config invalida."}), 400
    if not cfg.get("scenes"):
        return jsonify({"error":"Agrega al menos una escena."}), 400

    # imagenes subidas, en orden -> uploads[idx]
    uploads = []
    updir = os.path.join(PROYECTOS,"_uploads"); os.makedirs(updir, exist_ok=True)
    for f in request.files.getlist("uploads"):
        if not f or not f.filename:
            uploads.append(None); continue
        dest = os.path.join(updir, f"{uuid.uuid4().hex}_{f.filename}")
        f.save(dest); uploads.append(dest)
    # imagenes ya generadas en preview -> copiarlas para usarlas
    for s in cfg["scenes"]:
        if s.get("image_mode")=="preview" and s.get("preview_id"):
            pid = re.sub(r"[^a-f0-9]","",s["preview_id"])
            src = os.path.join(PROYECTOS,"_previews", pid + ".png")
            if os.path.exists(src):
                uploads.append(src); s["image_mode"]="upload"; s["upload_index"]=len(uploads)-1

    job = uuid.uuid4().hex
    JOBS[job] = {"estado":"trabajando","progreso":0,"total":0,"mensajes":[],
                 "video":None,"error":None,"carpeta":None}
    threading.Thread(target=producir_escenas, args=(job,cfg,uploads), daemon=True).start()
    return jsonify({"job":job, "escenas":len(cfg["scenes"])})

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
        os.startfile(j["carpeta"]); return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}),500

if __name__ == "__main__":
    os.makedirs(SALIDA_RAIZ, exist_ok=True)
    print("="*55)
    print("  ESTUDIO DE VIDEO IA v4  ->  http://127.0.0.1:5000")
    print("  Constructor de escenas | SDXL | LTX | lip-sync")
    print("  Salida organizada en:", SALIDA_RAIZ)
    print("="*55)
    app.run(host="127.0.0.1", port=5000, threaded=True)

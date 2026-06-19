# -*- coding: utf-8 -*-
"""
ESTUDIO DE VIDEO IA  -  App web local tipo ChatGPT
100% local / open source. NO usa Claude ni APIs de pago.
  - Genera clips con LTX-Video (ComfyUI en tu GPU)
  - Voz con edge-tts (es-MX, gratis)
  - Une todo con ffmpeg y exporta REEL 9:16 listo para TikTok/Shorts
Escribes un parrafo -> se divide en clips de ~5s -> tu PC hace todo sola.
"""
import os, re, json, time, uuid, threading, subprocess, math, shutil, urllib.request
from flask import Flask, request, jsonify, send_file, Response

# ---------------- Config ----------------
COMFY      = "http://127.0.0.1:8188"
COMFY_ROOT = r"C:\AI\ComfyUI_windows_portable\ComfyUI"
COMFY_OUT  = os.path.join(COMFY_ROOT, "output")
COMFY_IN   = os.path.join(COMFY_ROOT, "input")
PROYECTOS  = r"C:\AI\VideoStudio\proyectos"
DESKTOP    = os.path.join(os.path.expanduser("~"), "Desktop")
FONT_SRC   = r"C:\Windows\Fonts\arialbd.ttf"
CKPT       = "ltx-video-2b-v0.9.5.safetensors"
T5         = "t5xxl_fp8_e4m3fn_scaled.safetensors"
FPS        = 25
CHARS_POR_CLIP = 95     # ~5 segundos de narracion
SEG_POR_FOTO   = 2.5    # segundos que "dura" cada foto-ancla (keyframe)
MAX_SEG_CLIP   = 7      # tope de duracion por clip (seguro para la RTX 3070 de 8GB)
PY = __import__("sys").executable

app = Flask(__name__)
JOBS = {}   # job_id -> dict(estado, progreso, mensajes[], video, error)

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

def dividir_parrafo(texto, limite=CHARS_POR_CLIP):
    """Divide un parrafo en segmentos de ~limite caracteres respetando frases."""
    texto = texto.strip()
    # cortar en frases
    piezas = re.split(r'(?<=[\.\!\?\n])\s+', texto)
    frases = []
    for p in piezas:
        p = p.strip()
        if not p: continue
        # si una frase es muy larga, partir por comas / palabras
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
                    else:  # partir por palabras
                        palabras = s.split()
                        buf = ""
                        for w in palabras:
                            if len(buf) + len(w) + 1 <= limite:
                                buf = (buf + " " + w).strip()
                            else:
                                if buf: frases.append(buf)
                                buf = w
            if buf: frases.append(buf)
    # empaquetar frases hasta el limite
    segmentos, buf = [], ""
    for f in frases:
        if len(buf) + len(f) + 1 <= limite:
            buf = (buf + " " + f).strip()
        else:
            if buf: segmentos.append(buf)
            buf = f
    if buf: segmentos.append(buf)
    return segmentos or [texto[:limite]]

def srt_ts(seg):
    h = int(seg // 3600); m = int((seg % 3600)//60); s = int(seg % 60); ms = int((seg-int(seg))*1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

# ---------------- keyframes: colocacion de las fotos-ancla ----------------
def _snap8(f):
    """LTXVAddGuide exige que (frame_idx - 1) sea multiplo de 8 (o 0)."""
    return 0 if f <= 0 else ((f - 1) // 8) * 8 + 1

def _keyframe_indices(n, length):
    """Reparte n fotos a lo largo del clip: 1ra en 0, ultima cerca del final,
    intermedias uniformes; todas ajustadas a multiplos validos y crecientes."""
    if n <= 1:
        return [0]
    idxs = [_snap8(round(k * (length - 1) / (n - 1))) for k in range(n)]
    for i in range(1, len(idxs)):
        if idxs[i] <= idxs[i - 1]:
            idxs[i] = idxs[i - 1] + 8
    return idxs

def _largo_auto(n_fotos, segundos=None):
    """Duracion del clip. Con varias fotos: AUTO (mas fotos = mas largo), con tope
    seguro para 8GB. Si se pasa 'segundos' explicito, se respeta (acotado)."""
    if segundos is None:
        segundos = min(MAX_SEG_CLIP, max(3, (n_fotos or 1) * SEG_POR_FOTO))
    segundos = min(MAX_SEG_CLIP, max(2, segundos))
    return max(9, int(math.floor((segundos * FPS) / 8) * 8 + 1))

# ---------------- generacion de un clip via ComfyUI ----------------
def generar_clip(prompt, segundos, imagenes, out_file):
    """Genera un clip. `imagenes` es una LISTA de rutas (en orden). Con >=1 foto
    usa keyframes (LTXVAddGuide encadenado + LTXVCropGuides) para que el video se
    ancle en imagenes reales y NO derive a colores raros. Lista vacia = texto puro."""
    if isinstance(imagenes, str):
        imagenes = [imagenes] if imagenes else []
    imagenes = [p for p in (imagenes or []) if p and os.path.exists(p)]
    length = _largo_auto(len(imagenes), segundos)
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
        "12":{"class_type":"CreateVideo","inputs":{"images":["11",0],"fps":FPS}},
        "13":{"class_type":"SaveVideo","inputs":{"video":["12",0],"filename_prefix":"estudio_web/clip","format":"mp4","codec":"h264"}},
    }
    if imagenes:
        # Cadena de keyframes: una foto-ancla por nodo LTXVAddGuide.
        g["7"]={"class_type":"EmptyLTXVLatentVideo","inputs":{"width":768,"height":512,"length":length,"batch_size":1}}
        pos, neg_c, lat = ["3",0], ["4",0], ["7",0]
        fidx = _keyframe_indices(len(imagenes), length)
        for k, ruta in enumerate(imagenes):
            name = f"webkf_{k}_{os.path.basename(ruta)}"
            shutil.copy(ruta, os.path.join(COMFY_IN, name))
            ld, ag = str(20+k), str(30+k)
            g[ld]={"class_type":"LoadImage","inputs":{"image":name}}
            g[ag]={"class_type":"LTXVAddGuide","inputs":{"positive":pos,"negative":neg_c,"vae":["1",2],"latent":lat,"image":[ld,0],"frame_idx":fidx[k],"strength":1.0}}
            pos, neg_c, lat = [ag,0], [ag,1], [ag,2]
        g["8"]["inputs"]["latent"]=lat
        g["10"]={"class_type":"SamplerCustom","inputs":{"model":["6",0],"add_noise":True,"noise_seed":seed,"cfg":3.0,"positive":pos,"negative":neg_c,"sampler":["9",0],"sigmas":["8",0],"latent_image":lat}}
        # Quita los frames-guia insertados antes de decodificar.
        g["14"]={"class_type":"LTXVCropGuides","inputs":{"positive":pos,"negative":neg_c,"latent":["10",0]}}
        g["11"]={"class_type":"VAEDecode","inputs":{"samples":["14",2],"vae":["1",2]}}
    else:
        g["5"]={"class_type":"LTXVConditioning","inputs":{"positive":["3",0],"negative":["4",0],"frame_rate":FPS}}
        g["7"]={"class_type":"EmptyLTXVLatentVideo","inputs":{"width":768,"height":512,"length":length,"batch_size":1}}
        g["8"]["inputs"]["latent"]=["7",0]
        g["10"]={"class_type":"SamplerCustom","inputs":{"model":["6",0],"add_noise":True,"noise_seed":seed,"cfg":3.0,"positive":["5",0],"negative":["5",1],"sampler":["9",0],"sigmas":["8",0],"latent_image":["7",0]}}
        g["11"]={"class_type":"VAEDecode","inputs":{"samples":["10",0],"vae":["1",2]}}

    data = json.dumps({"prompt":g,"client_id":"webapp"}).encode("utf-8")
    req = urllib.request.Request(COMFY+"/prompt", data=data, headers={"Content-Type":"application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
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
                newest = max(mp4s, key=os.path.getmtime)
                shutil.copy(newest, out_file)
                return out_file
    return None

# ---------------- pipeline completo ----------------
def producir(job, texto, voz, imagenes):
    try:
        imagenes = [p for p in (imagenes or []) if p and os.path.exists(p)]
        pdir = os.path.join(PROYECTOS, "reel_" + job[:8])
        clips_d = os.path.join(pdir,"clips"); sal_d = os.path.join(pdir,"salida")
        os.makedirs(clips_d, exist_ok=True); os.makedirs(sal_d, exist_ok=True)
        shutil.copy(FONT_SRC, os.path.join(pdir,"fuente.ttf"))

        if not comfy_vivo():
            log(job,"Iniciando ComfyUI (espera ~1 min la primera vez)...")
            subprocess.Popen([r"C:\AI\ComfyUI_windows_portable\INICIAR_ComfyUI_RTX3070.bat"], shell=True)
            for _ in range(80):
                time.sleep(3)
                if comfy_vivo(): break

        if imagenes:
            # MODO STORYBOARD: tus fotos son las anclas del video (en orden). Un solo
            # clip, mas largo entre mas fotos, sin partes abstractas. Todo el texto = voz.
            segmentos = [texto]
            log(job, f"Animando {len(imagenes)} foto(s) como un clip anclado. Empezando...")
        else:
            segmentos = dividir_parrafo(texto)
            log(job, f"Tu idea se dividio en {len(segmentos)} clip(s) de ~5s. Empezando...")
        JOBS[job]["total"] = len(segmentos)

        escenas = []; srt_lines = []; t_acc = 0.0
        prev_last = None   # ultimo frame del clip anterior (continuidad sin fotos)
        for i, seg in enumerate(segmentos, 1):
            JOBS[job]["progreso"] = i
            log(job, f"Clip {i}/{len(segmentos)}: generando voz...")
            voz_mp3 = os.path.join(sal_d, f"voz_{i}.mp3")
            txtf = os.path.join(sal_d, f"seg_{i}.txt")
            open(txtf,"w",encoding="utf-8").write(seg)
            subprocess.run([PY,"-m","edge_tts","-f",txtf,"-v",voz,"--write-media",voz_mp3],
                           capture_output=True)
            vdur = ffprobe_dur(voz_mp3) or 4.0
            csec = min(8, max(3, math.ceil(vdur)))

            log(job, f"Clip {i}/{len(segmentos)}: generando video en la GPU...")
            clip_mp4 = os.path.join(clips_d, f"clip_{i:03d}.mp4")
            if imagenes:
                imgs_clip, dur_clip = imagenes, None       # storyboard: largo AUTO
            elif prev_last:
                imgs_clip, dur_clip = [prev_last], csec     # continua donde acabo el anterior
            else:
                imgs_clip, dur_clip = [], csec              # 1er clip de texto puro
            if not generar_clip(seg, dur_clip, imgs_clip, clip_mp4):
                log(job, f"  (Clip {i} fallo, lo salto)")
                continue
            # Continuidad: guarda el ultimo frame para arrancar el siguiente clip ahi
            # (asi ningun clip sale abstracto). Solo en el pipeline sin fotos.
            if not imagenes:
                prev_last = os.path.join(sal_d, f"last_{i:03d}.png")
                subprocess.run(["ffmpeg","-y","-sseof","-0.1","-i",clip_mp4,
                                "-frames:v","1",prev_last], capture_output=True)
                if not os.path.exists(prev_last):
                    prev_last = None

            # escena = video + su voz (video manda la duracion, audio se rellena con silencio)
            escena = os.path.join(sal_d, f"escena_{i:03d}.mp4")
            subprocess.run(["ffmpeg","-i",clip_mp4,"-i",voz_mp3,"-map","0:v","-map","1:a",
                            "-af","apad","-shortest","-c:v","libx264","-pix_fmt","yuv420p",
                            "-c:a","aac","-y",escena], capture_output=True)
            cdur = ffprobe_dur(escena) or csec
            srt_lines.append(f"{len(escenas)+1}\n{srt_ts(t_acc)} --> {srt_ts(t_acc+cdur)}\n{seg}\n")
            t_acc += cdur
            escenas.append(escena)

        if not escenas:
            JOBS[job]["estado"]="error"; JOBS[job]["error"]="No se genero ningun clip."; return

        # concatenar escenas
        log(job,"Uniendo todos los clips...")
        lista = os.path.join(sal_d,"lista.txt")
        with open(lista,"w",encoding="utf-8") as f:
            for e in escenas: f.write(f"file '{e.replace(chr(92),'/')}'\n")
        combinado = os.path.join(sal_d,"combinado.mp4")
        subprocess.run(["ffmpeg","-f","concat","-safe","0","-i",lista,
                        "-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-y",combinado],
                       capture_output=True)

        # subtitulos
        srt = os.path.join(sal_d,"subs.srt")
        open(srt,"w",encoding="utf-8").write("\n".join(srt_lines))

        # exportar REEL 9:16 con fondo difuminado + subtitulos quemados
        log(job,"Exportando REEL 9:16 para TikTok/Shorts...")
        final = os.path.join(sal_d,"REEL_FINAL.mp4")
        fc = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:4[bg];"
              "[0:v]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,subtitles=subs.srt[v]")
        old = os.getcwd(); os.chdir(sal_d)
        subprocess.run(["ffmpeg","-i","combinado.mp4","-filter_complex",fc,"-map","[v]","-map","0:a",
                        "-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-y","REEL_FINAL.mp4"],
                       capture_output=True)
        os.chdir(old)

        if not os.path.exists(final):
            JOBS[job]["estado"]="error"; JOBS[job]["error"]="Fallo el export final."; return

        # copiar al escritorio
        dest = os.path.join(DESKTOP, f"REEL_{job[:6]}.mp4")
        shutil.copy(final, dest)
        JOBS[job]["video"] = final
        JOBS[job]["desktop"] = dest
        JOBS[job]["estado"]="listo"
        log(job, f"LISTO! Reel exportado. Tambien lo copie a tu Escritorio: {os.path.basename(dest)}")
    except Exception as ex:
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
    if not texto:
        return jsonify({"error":"Escribe tu idea primero."}), 400
    # Acepta VARIAS fotos (en orden). Compat: tambien lee el viejo campo "imagen".
    files = request.files.getlist("imagenes") + request.files.getlist("imagen")
    imagenes = []
    if files:
        updir = os.path.join(PROYECTOS,"_uploads"); os.makedirs(updir, exist_ok=True)
        for f in files:
            if not f or not f.filename: continue
            dest = os.path.join(updir, f"{uuid.uuid4().hex}_{f.filename}")
            f.save(dest); imagenes.append(dest)
    job = uuid.uuid4().hex
    JOBS[job] = {"estado":"trabajando","progreso":0,"total":0,"mensajes":[],"video":None,"error":None}
    threading.Thread(target=producir, args=(job,texto,voz,imagenes), daemon=True).start()
    n = 1 if imagenes else len(dividir_parrafo(texto))
    return jsonify({"job":job, "clips_estimados":n})

@app.route("/api/status/<job>")
def api_status(job):
    j = JOBS.get(job)
    if not j: return jsonify({"error":"no existe"}),404
    return jsonify({"estado":j["estado"],"progreso":j["progreso"],"total":j["total"],
                    "mensajes":j["mensajes"],"error":j["error"],
                    "tiene_video": j["video"] is not None})

@app.route("/api/video/<job>")
def api_video(job):
    j = JOBS.get(job)
    if not j or not j["video"]: return "no listo",404
    return send_file(j["video"], mimetype="video/mp4")

@app.route("/api/estimar", methods=["POST"])
def api_estimar():
    data = request.get_json(force=True, silent=True) or {}
    texto = data.get("texto","")
    return jsonify({"clips": len(dividir_parrafo(texto)), "chars_por_clip": CHARS_POR_CLIP})

if __name__ == "__main__":
    print("="*55)
    print("  ESTUDIO DE VIDEO IA  ->  http://127.0.0.1:5000")
    print("="*55)
    app.run(host="127.0.0.1", port=5000, threaded=True)

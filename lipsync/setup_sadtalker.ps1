# ============================================================
#  setup_sadtalker.ps1  -  Instala SadTalker en entorno AISLADO
#  (Python 3.10 en C:\AI\lipsync\python). NO toca ComfyUI ni el sistema.
#  Todo lo que escribe queda bajo C:\AI\lipsync\.
# ============================================================
$ErrorActionPreference = "Continue"
$base = "C:\AI\lipsync"
$py   = "$base\python\python.exe"
$log  = "$base\setup_log.txt"
function Say($m){ $t = (Get-Date).ToString("HH:mm:ss"); "$t  $m" | Tee-Object -FilePath $log -Append }

"==== SETUP SADTALKER $(Get-Date) ====" | Set-Content $log

Say "1/6 pip + wheel..."
& $py -m pip install --upgrade pip wheel setuptools 2>&1 | Tee-Object -FilePath $log -Append

Say "2/6 PyTorch CUDA 11.8 (torch 2.0.1 / torchvision 0.15.2)... (descarga grande)"
& $py -m pip install torch==2.0.1+cu118 torchvision==0.15.2+cu118 --index-url https://download.pytorch.org/whl/cu118 2>&1 | Tee-Object -FilePath $log -Append

Say "3/6 Clonando SadTalker..."
if (-not (Test-Path "$base\SadTalker")) {
  git clone https://github.com/OpenTalker/SadTalker "$base\SadTalker" 2>&1 | Tee-Object -FilePath $log -Append
} else { Say "  (ya existe SadTalker)" }

Say "4/6 Dependencias de SadTalker (pinneadas para Python 3.10)..."
$deps = @(
  "numpy==1.23.4","face_alignment==1.3.5","imageio==2.19.3","imageio-ffmpeg==0.4.7",
  "librosa==0.9.2","numba==0.58.1","resampy==0.3.1","pydub==0.25.1","scipy==1.10.1",
  "kornia==0.6.8","tqdm","yacs==0.1.8","pyyaml","joblib==1.1.0","scikit-image==0.19.3",
  "basicsr==1.4.2","facexlib==0.3.0","gfpgan==1.3.8","av","safetensors"
)
& $py -m pip install @deps 2>&1 | Tee-Object -FilePath $log -Append

Say "5/6 Descargando modelos de SadTalker..."
$ck = "$base\SadTalker\checkpoints"; New-Item -ItemType Directory -Force -Path $ck | Out-Null
$gf = "$base\SadTalker\gfpgan\weights"; New-Item -ItemType Directory -Force -Path $gf | Out-Null
$models = @{
  "$ck\mapping_00109-model.pth.tar"        = "https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/mapping_00109-model.pth.tar"
  "$ck\mapping_00229-model.pth.tar"        = "https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/mapping_00229-model.pth.tar"
  "$ck\SadTalker_V0.0.2_256.safetensors"   = "https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/SadTalker_V0.0.2_256.safetensors"
  "$ck\SadTalker_V0.0.2_512.safetensors"   = "https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/SadTalker_V0.0.2_512.safetensors"
  "$gf\alignment_WFLW_4HG.pth"             = "https://github.com/xinntao/facexlib/releases/download/v0.1.0/alignment_WFLW_4HG.pth"
  "$gf\detection_Resnet50_Final.pth"       = "https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth"
  "$gf\parsing_parsenet.pth"               = "https://github.com/xinntao/facexlib/releases/download/v0.2.2/parsing_parsenet.pth"
  "$gf\GFPGANv1.4.pth"                     = "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.4/GFPGANv1.4.pth"
}
foreach ($dst in $models.Keys) {
  if (Test-Path $dst) { Say "  ya existe: $(Split-Path $dst -Leaf)"; continue }
  Say "  bajando: $(Split-Path $dst -Leaf)"
  curl.exe -L --fail -s -o $dst $models[$dst]
  if ($LASTEXITCODE -ne 0) { Say "  !! fallo descarga $(Split-Path $dst -Leaf)" }
}

Say "6/6 Verificando import de SadTalker..."
$test = @"
import sys
sys.path.insert(0, r'$base\SadTalker')
ok = True
try:
    import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())
    import face_alignment, librosa, kornia, yacs, safetensors
    import basicsr, gfpgan, facexlib
    from src.utils.preprocess import CropAndExtract
    from src.test_audio2coeff import Audio2Coeff
    from src.facerender.animate import AnimateFromCoeff
    print('IMPORT_OK')
except Exception as e:
    ok = False
    import traceback; traceback.print_exc()
    print('IMPORT_FAIL')
"@
$test | Set-Content "$base\_import_test.py" -Encoding utf8
& $py "$base\_import_test.py" 2>&1 | Tee-Object -FilePath $log -Append

Say "==== FIN SETUP ===="

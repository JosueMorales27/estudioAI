# Organizador de modelos: barre Descargas y manda cada modelo a su carpeta de ComfyUI.
# Seguro de re-ejecutar las veces que quieras. Salta archivos a medio bajar.
$dl = "$env:USERPROFILE\Downloads"
$m  = "C:\AI\ComfyUI_windows_portable\ComfyUI\models"

$rules = @(
  @{pat='wan*14B*.safetensors';    dest='diffusion_models'},
  @{pat='*t2v*14B*.safetensors';   dest='diffusion_models'},
  @{pat='*i2v*14B*.safetensors';   dest='diffusion_models'},
  @{pat='umt5*.safetensors';       dest='text_encoders'},
  @{pat='t5xxl*.safetensors';      dest='text_encoders'},
  @{pat='*vae*.safetensors';       dest='vae'},
  @{pat='*lightx2v*.safetensors';  dest='loras'},
  @{pat='*lora*.safetensors';      dest='loras'},
  @{pat='ltx-video*.safetensors';  dest='checkpoints'}
)

$now = Get-Date
$moved = 0
foreach($r in $rules){
  Get-ChildItem $dl -Filter $r.pat -File -ErrorAction SilentlyContinue | ForEach-Object {
    if($_.Extension -eq '.crdownload'){ return }
    if(($now - $_.LastWriteTime).TotalSeconds -lt 30){ Write-Host "SALTADO (aun bajando): $($_.Name)"; return }
    $target = Join-Path $m $r.dest
    if(-not (Test-Path $target)){ New-Item -ItemType Directory -Path $target -Force | Out-Null }
    $finalPath = Join-Path $target $_.Name
    if(Test-Path $finalPath){ Write-Host "YA EXISTE: $($_.Name)"; return }
    Move-Item $_.FullName $finalPath -Force
    Write-Host "MOVIDO: $($_.Name) -> models\$($r.dest)"
    $moved++
  }
}
Write-Host "`nListo. $moved archivo(s) organizado(s)."

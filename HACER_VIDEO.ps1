# ============================================================
#  HACER_VIDEO.ps1  -  Generador de video IA local (LTX-Video)
#  Uso:
#    .\HACER_VIDEO.ps1 -Prompt "tu descripcion en ingles"
#    .\HACER_VIDEO.ps1 -Prompt "..." -Imagen "C:\ruta\foto.jpg"   (imagen de referencia)
#    .\HACER_VIDEO.ps1 -Prompt "..." -Segundos 5 -W 768 -H 512
# ============================================================
param(
  [Parameter(Mandatory=$true)][string]$Prompt,
  [string]$Imagen = "",
  [string[]]$Imagenes = @(),
  [string]$ImagenesStr = "",
  [double]$Segundos = 4,
  [int]$W = 768,
  [int]$H = 512,
  [int]$Pasos = 30,
  [int]$Seed = 0,
  [string]$Negativo = "blurry, low quality, distorted, deformed, static, watermark, text, jpeg artifacts"
)

$server = "http://127.0.0.1:8188"
$outDir = "C:\AI\ComfyUI_windows_portable\ComfyUI\output"
$inputDir = "C:\AI\ComfyUI_windows_portable\ComfyUI\input"

# Verificar que ComfyUI este corriendo
$code = curl.exe -s -o NUL -w "%{http_code}" "$server/system_stats"
if($code -ne "200"){ Write-Host "ComfyUI no responde. Abre primero el acceso directo 'ComfyUI (RTX 3070)'." -ForegroundColor Red; exit 1 }

# Junta imagen unica (compat) + lista + cadena separada por ';' (desde el .bat),
# en orden. Varias fotos = anclas (keyframes).
$imgs = @(); if($Imagen){ $imgs += $Imagen }; $imgs += $Imagenes
if($ImagenesStr){ $imgs += ($ImagenesStr -split ';' | Where-Object { $_ }) }
$imgs = @($imgs | ForEach-Object { $_.Trim('"',' ') } | Where-Object { $_ -and (Test-Path $_) })
$n = $imgs.Count

# Largo en frames (multiplo de 8 + 1). Con varias fotos: AUTO (mas fotos = mas
# largo), con tope de 7s seguro para 8GB.
$fps = 25; $maxSeg = 7
if($n -gt 1){ $auto = [math]::Min($maxSeg, [math]::Max(3, $n*2.5)); if($Segundos -lt $auto){ $Segundos = $auto } }
if($Segundos -gt $maxSeg){ $Segundos = $maxSeg }
$len = [math]::Floor(($Segundos * $fps) / 8) * 8 + 1
if($len -lt 9){ $len = 9 }
if($Seed -eq 0){ $Seed = Get-Random -Minimum 1 -Maximum 2147483000 }

Write-Host "Generando video: ${W}x${H}, $len frames (~$([math]::Round($len/$fps,1))s), $Pasos pasos, seed $Seed" -ForegroundColor Cyan
if($n -ge 1){ Write-Host "Con $n foto(s)-ancla (keyframes)." -ForegroundColor Cyan }

# --- Construir el grafo ---
$g = @{}
$g["1"] = @{class_type="CheckpointLoaderSimple"; inputs=@{ckpt_name="ltx-video-2b-v0.9.5.safetensors"}}
$g["2"] = @{class_type="CLIPLoader"; inputs=@{clip_name="t5xxl_fp8_e4m3fn_scaled.safetensors"; type="ltxv"}}
$g["3"] = @{class_type="CLIPTextEncode"; inputs=@{text=$Prompt; clip=@("2",0)}}
$g["4"] = @{class_type="CLIPTextEncode"; inputs=@{text=$Negativo; clip=@("2",0)}}
$g["6"] = @{class_type="ModelSamplingLTXV"; inputs=@{model=@("1",0); max_shift=2.05; base_shift=0.95}}
$g["9"] = @{class_type="KSamplerSelect"; inputs=@{sampler_name="euler"}}

if($n -ge 1){
  # Cadena de keyframes: una foto-ancla por nodo LTXVAddGuide; (frame_idx-1) mult de 8.
  $g["7"] = @{class_type="EmptyLTXVLatentVideo"; inputs=@{width=$W; height=$H; length=$len; batch_size=1}}
  $posSrc=@("3",0); $negSrc=@("4",0); $latSrc=@("7",0)
  for($k=0; $k -lt $n; $k++){
    if($n -eq 1){ $f = 0 } else { $f = [int][math]::Round($k*($len-1)/($n-1)) }
    if($f -le 0){ $fi = 0 } else { $fi = [math]::Floor(($f-1)/8)*8 + 1 }
    $imgName = "kf_${k}_" + [System.IO.Path]::GetFileName($imgs[$k])
    Copy-Item $imgs[$k] (Join-Path $inputDir $imgName) -Force
    $ld = "$(20+$k)"; $ag = "$(30+$k)"
    $g[$ld] = @{class_type="LoadImage"; inputs=@{image=$imgName}}
    $g[$ag] = @{class_type="LTXVAddGuide"; inputs=@{positive=$posSrc; negative=$negSrc; vae=@("1",2); latent=$latSrc; image=@($ld,0); frame_idx=$fi; strength=1.0}}
    $posSrc=@($ag,0); $negSrc=@($ag,1); $latSrc=@($ag,2)
  }
  $g["8"]  = @{class_type="LTXVScheduler"; inputs=@{steps=$Pasos; max_shift=2.05; base_shift=0.95; stretch=$true; terminal=0.1; latent=$latSrc}}
  $g["10"] = @{class_type="SamplerCustom"; inputs=@{model=@("6",0); add_noise=$true; noise_seed=$Seed; cfg=3.0; positive=$posSrc; negative=$negSrc; sampler=@("9",0); sigmas=@("8",0); latent_image=$latSrc}}
  $g["14"] = @{class_type="LTXVCropGuides"; inputs=@{positive=$posSrc; negative=$negSrc; latent=@("10",0)}}
  $g["11"] = @{class_type="VAEDecode"; inputs=@{samples=@("14",2); vae=@("1",2)}}
} else {
  $g["5"] = @{class_type="LTXVConditioning"; inputs=@{positive=@("3",0); negative=@("4",0); frame_rate=$fps}}
  $g["7"] = @{class_type="EmptyLTXVLatentVideo"; inputs=@{width=$W; height=$H; length=$len; batch_size=1}}
  $g["8"]  = @{class_type="LTXVScheduler"; inputs=@{steps=$Pasos; max_shift=2.05; base_shift=0.95; stretch=$true; terminal=0.1; latent=@("7",0)}}
  $g["10"] = @{class_type="SamplerCustom"; inputs=@{model=@("6",0); add_noise=$true; noise_seed=$Seed; cfg=3.0; positive=@("5",0); negative=@("5",1); sampler=@("9",0); sigmas=@("8",0); latent_image=@("7",0)}}
  $g["11"] = @{class_type="VAEDecode"; inputs=@{samples=@("10",0); vae=@("1",2)}}
}
$g["12"] = @{class_type="CreateVideo"; inputs=@{images=@("11",0); fps=$fps}}
$g["13"] = @{class_type="SaveVideo"; inputs=@{video=@("12",0); filename_prefix="video_ia/MiVideo"; format="mp4"; codec="h264"}}

$body = @{prompt=$g; client_id="hacer_video_ps"} | ConvertTo-Json -Depth 12 -Compress
$tmp = Join-Path $env:TEMP "hacer_video_body.json"
[System.IO.File]::WriteAllText($tmp, $body)

$resp = (curl.exe -s -X POST -H "Content-Type: application/json" --data-binary "@$tmp" "$server/prompt") | ConvertFrom-Json
if(-not $resp.prompt_id){ Write-Host "Error al encolar: $resp" -ForegroundColor Red; exit 1 }
$jobId = $resp.prompt_id
Write-Host "Encolado ($jobId). Renderizando..." -ForegroundColor Yellow

# Esperar (parseo por texto crudo para evitar problemas de tipos en PS5)
for($i=0; $i -lt 240; $i++){
  Start-Sleep -Seconds 5
  $raw = (curl.exe -s "$server/history/$jobId")
  if([string]::IsNullOrWhiteSpace($raw)){ continue }
  if($raw -notmatch [regex]::Escape($jobId)){ continue }
  if($raw -match '"status_str":\s*"error"'){ Write-Host "Fallo el render. Revisa la consola de ComfyUI." -ForegroundColor Red; exit 1 }
  if($raw -match '"completed":\s*true'){
    # Toma el mp4 mas reciente de output\video_ia (robusto: evita parsear el JSON
    # del history, cuya estructura cambia entre versiones de ComfyUI/SaveVideo).
    Start-Sleep -Milliseconds 500
    $latest = Get-ChildItem (Join-Path $outDir "video_ia") -Filter *.mp4 -EA SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if(-not $latest){ Write-Host "Render OK pero no encontre el archivo." -ForegroundColor Red; exit 1 }
    $dst = Join-Path ([Environment]::GetFolderPath("Desktop")) $latest.Name
    Copy-Item $latest.FullName $dst -Force
    Write-Host "`nLISTO! Video guardado en:" -ForegroundColor Green
    Write-Host "  $dst" -ForegroundColor Green
    Start-Process $dst
    exit 0
  }
}
Write-Host "Tardo demasiado (timeout). Revisa ComfyUI." -ForegroundColor Red

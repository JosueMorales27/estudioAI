# ================================================================
#   lib.ps1  -  Funciones del Estudio de Video IA (compartidas)
# ================================================================
$script:server   = "http://127.0.0.1:8188"
$script:comfyOut = "C:\AI\ComfyUI_windows_portable\ComfyUI\output"
$script:comfyIn  = "C:\AI\ComfyUI_windows_portable\ComfyUI\input"
$script:fps      = 25

function ComfyVivo {
  try { return (curl.exe -s -o NUL -w "%{http_code}" "$server/system_stats") -eq "200" } catch { return $false }
}

function Generar-Clip {
  # -Imagenes: arreglo de rutas EN ORDEN (1ra=inicio, ultima=final). Con varias
  # fotos usa keyframes (LTXVAddGuide encadenado + LTXVCropGuides) para que el
  # video se ancle en imagenes reales y NO derive a colores raros. Vacio = texto.
  param([string]$Prompt,[string[]]$Imagenes,[double]$Segundos,[int]$W,[int]$H,[int]$Pasos,[string]$OutFile)
  $maxSeg = 7   # tope seguro para la RTX 3070 de 8GB
  $imgs = @($Imagenes | Where-Object { $_ -and (Test-Path $_) })
  $n = $imgs.Count
  # Duracion AUTO: mas fotos = mas largo (acotado). Si pasan $Segundos, se respeta.
  if($n -gt 1){ $auto = [math]::Min($maxSeg, [math]::Max(3, $n*2.5)); if($Segundos -lt $auto){ $Segundos = $auto } }
  if($Segundos -le 0){ $Segundos = [math]::Max(3, $n*2.5) }
  if($Segundos -gt $maxSeg){ $Segundos = $maxSeg }
  $len = [math]::Floor(($Segundos*$fps)/8)*8 + 1
  if($len -lt 9){ $len = 9 }
  $seed = Get-Random -Minimum 1 -Maximum 2147483000
  $neg  = "blurry, low quality, distorted, deformed, static, watermark, text, jpeg artifacts"
  $g = @{}
  $g["1"] = @{class_type="CheckpointLoaderSimple"; inputs=@{ckpt_name="ltx-video-2b-v0.9.5.safetensors"}}
  $g["2"] = @{class_type="CLIPLoader"; inputs=@{clip_name="t5xxl_fp8_e4m3fn_scaled.safetensors"; type="ltxv"}}
  $g["3"] = @{class_type="CLIPTextEncode"; inputs=@{text=$Prompt; clip=@("2",0)}}
  $g["4"] = @{class_type="CLIPTextEncode"; inputs=@{text=$neg; clip=@("2",0)}}
  $g["6"] = @{class_type="ModelSamplingLTXV"; inputs=@{model=@("1",0); max_shift=2.05; base_shift=0.95}}
  $g["9"] = @{class_type="KSamplerSelect"; inputs=@{sampler_name="euler"}}
  if($n -ge 1){
    # Reparte las fotos a lo largo del clip; (frame_idx-1) debe ser multiplo de 8 (o 0).
    $g["7"] = @{class_type="EmptyLTXVLatentVideo"; inputs=@{width=$W; height=$H; length=$len; batch_size=1}}
    $pos=@("3",0); $neg2=@("4",0); $lat=@("7",0)
    for($k=0; $k -lt $n; $k++){
      if($n -eq 1){ $f = 0 } else { $f = [int][math]::Round($k*($len-1)/($n-1)) }
      if($f -le 0){ $fi = 0 } else { $fi = [math]::Floor(($f-1)/8)*8 + 1 }
      $imgName = "kf_${k}_" + ([System.IO.Path]::GetFileName($imgs[$k]))
      Copy-Item $imgs[$k] (Join-Path $comfyIn $imgName) -Force
      $ld = "$(20+$k)"; $ag = "$(30+$k)"
      $g[$ld] = @{class_type="LoadImage"; inputs=@{image=$imgName}}
      $g[$ag] = @{class_type="LTXVAddGuide"; inputs=@{positive=$pos; negative=$neg2; vae=@("1",2); latent=$lat; image=@($ld,0); frame_idx=$fi; strength=1.0}}
      $pos=@($ag,0); $neg2=@($ag,1); $lat=@($ag,2)
    }
    $g["8"]  = @{class_type="LTXVScheduler"; inputs=@{steps=$Pasos; max_shift=2.05; base_shift=0.95; stretch=$true; terminal=0.1; latent=$lat}}
    $g["10"] = @{class_type="SamplerCustom"; inputs=@{model=@("6",0); add_noise=$true; noise_seed=$seed; cfg=3.0; positive=$pos; negative=$neg2; sampler=@("9",0); sigmas=@("8",0); latent_image=$lat}}
    $g["14"] = @{class_type="LTXVCropGuides"; inputs=@{positive=$pos; negative=$neg2; latent=@("10",0)}}
    $g["11"] = @{class_type="VAEDecode"; inputs=@{samples=@("14",2); vae=@("1",2)}}
  } else {
    $g["5"] = @{class_type="LTXVConditioning"; inputs=@{positive=@("3",0); negative=@("4",0); frame_rate=$fps}}
    $g["7"] = @{class_type="EmptyLTXVLatentVideo"; inputs=@{width=$W; height=$H; length=$len; batch_size=1}}
    $g["8"]  = @{class_type="LTXVScheduler"; inputs=@{steps=$Pasos; max_shift=2.05; base_shift=0.95; stretch=$true; terminal=0.1; latent=@("7",0)}}
    $g["10"] = @{class_type="SamplerCustom"; inputs=@{model=@("6",0); add_noise=$true; noise_seed=$seed; cfg=3.0; positive=@("5",0); negative=@("5",1); sampler=@("9",0); sigmas=@("8",0); latent_image=@("7",0)}}
    $g["11"] = @{class_type="VAEDecode"; inputs=@{samples=@("10",0); vae=@("1",2)}}
  }
  $g["12"] = @{class_type="CreateVideo"; inputs=@{images=@("11",0); fps=$fps}}
  $g["13"] = @{class_type="SaveVideo"; inputs=@{video=@("12",0); filename_prefix="estudio/clip"; format="mp4"; codec="h264"}}
  $body = @{prompt=$g; client_id="estudio_ia"} | ConvertTo-Json -Depth 12 -Compress
  $tmp = Join-Path $env:TEMP "estudio_body.json"
  [System.IO.File]::WriteAllText($tmp, $body)
  $resp = (curl.exe -s -X POST -H "Content-Type: application/json" --data-binary "@$tmp" "$server/prompt") | ConvertFrom-Json
  if(-not $resp.prompt_id){ Write-Host "Error al encolar." -ForegroundColor Red; return $null }
  $jobId = $resp.prompt_id
  Write-Host "  Renderizando ($([math]::Round($len/$fps,1))s, ${W}x${H}, $Pasos pasos)..." -ForegroundColor Yellow
  for($i=0; $i -lt 240; $i++){
    Start-Sleep -Seconds 4
    $raw = (curl.exe -s "$server/history/$jobId")
    if([string]::IsNullOrWhiteSpace($raw)){ continue }
    if($raw -notmatch [regex]::Escape($jobId)){ continue }
    if($raw -match '"status_str":\s*"error"'){ Write-Host "  Fallo el render." -ForegroundColor Red; return $null }
    if($raw -match '"completed":\s*true'){
      # Tomar el mp4 mas reciente de output\estudio (evita parsear JSON, robusto en PS5)
      Start-Sleep -Milliseconds 500
      $latest = Get-ChildItem (Join-Path $comfyOut "estudio") -Filter *.mp4 -EA SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
      if($latest){
        Copy-Item $latest.FullName $OutFile -Force
        Write-Host "  Clip listo -> $OutFile" -ForegroundColor Green
        return $OutFile
      }
      Write-Host "  Render OK pero no se encontro el archivo." -ForegroundColor Red; return $null
    }
  }
  Write-Host "  Timeout." -ForegroundColor Red; return $null
}

function Generar-Voz {
  param([string]$Texto,[string]$Voz,[string]$OutMp3,[string]$OutSrt)
  $txtFile = Join-Path $env:TEMP "estudio_voz.txt"
  [System.IO.File]::WriteAllText($txtFile, $Texto, (New-Object System.Text.UTF8Encoding $false))
  python -m edge_tts -f $txtFile -v $Voz --write-media $OutMp3 --write-subtitles $OutSrt
  if(Test-Path $OutMp3){ Write-Host "  Voz lista -> $OutMp3" -ForegroundColor Green; return $true }
  Write-Host "  Fallo la voz." -ForegroundColor Red; return $false
}

function Montar-Final {
  param([string[]]$Clips,[string]$VozMp3,[string]$Srt,[string]$OutFile,[int]$W,[int]$H)
  $work = Split-Path $OutFile -Parent
  Push-Location $work
  try {
    $inputs = @(); $filters = @(); $labels = ""
    for($k=0; $k -lt $Clips.Count; $k++){
      $inputs += "-i"; $inputs += $Clips[$k]
      $filters += "[${k}:v]scale=${W}:${H},setsar=1,fps=$fps[v$k]"
      $labels += "[v$k]"
    }
    $concat = ($filters -join ";") + ";" + $labels + "concat=n=$($Clips.Count):v=1:a=0[vout]"
    $tempA = Join-Path $work "_concat.mp4"
    if($VozMp3 -and (Test-Path $VozMp3)){
      $audioIdx = $Clips.Count
      $ffargs = $inputs + @("-i",$VozMp3,"-filter_complex",$concat,"-map","[vout]","-map","${audioIdx}:a","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-shortest","-y",$tempA)
    } else {
      $ffargs = $inputs + @("-filter_complex",$concat,"-map","[vout]","-c:v","libx264","-pix_fmt","yuv420p","-y",$tempA)
    }
    Write-Host "  Uniendo clips + audio..." -ForegroundColor Yellow
    & ffmpeg @ffargs 2>$null
    if(-not (Test-Path $tempA)){ Write-Host "  Fallo al unir los clips." -ForegroundColor Red; return $false }

    $haySubs = $Srt -and (Test-Path $Srt) -and ((Get-Item $Srt).Length -gt 10)
    if($haySubs){
      Write-Host "  Quemando subtitulos..." -ForegroundColor Yellow
      $srtName = Split-Path $Srt -Leaf
      & ffmpeg -i "_concat.mp4" -vf "subtitles=$srtName" -c:a copy -y $OutFile 2>$null
      if(Test-Path $OutFile){ Remove-Item $tempA -Force -EA SilentlyContinue }
      else { Write-Host "  (No se pudieron quemar subtitulos; dejo el video sin ellos)" -ForegroundColor DarkYellow; Move-Item $tempA $OutFile -Force }
    } else {
      Move-Item $tempA $OutFile -Force
    }
  } finally { Pop-Location }
  if(Test-Path $OutFile){ Write-Host "  VIDEO FINAL -> $OutFile" -ForegroundColor Green; return $true }
  return $false
}

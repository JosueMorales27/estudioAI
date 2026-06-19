# Ensambla el meme: clips + musica AC/DC + voz + texto gigante
$p = "C:\AI\VideoStudio\proyectos\biometricos"
$c = Join-Path $p "clips"
$s = Join-Path $p "salida"
$music = "C:\Users\IntelGuy\Desktop\JARVIS\music\ac dc - back in black.mp3"
$W = 768; $H = 512; $fps = 25
$clips = @(Get-ChildItem $c -Filter *.mp4 | Sort-Object Name | Select-Object -ExpandProperty FullName)
if($clips.Count -eq 0){ Write-Host "No hay clips!" -ForegroundColor Red; exit 1 }

Push-Location $p
try {
  # copiar el font a la carpeta (evita el problema del ':' en rutas de ffmpeg)
  Copy-Item "C:\Windows\Fonts\arialbd.ttf" (Join-Path $p "fuente.ttf") -Force
  # --- Stage 1: unir clips (solo video) ---
  $inputs=@(); $filters=@(); $labels=""
  for($k=0;$k -lt $clips.Count;$k++){ $inputs+="-i"; $inputs+=$clips[$k]; $filters+="[${k}:v]scale=${W}:${H},setsar=1,fps=$fps[v$k]"; $labels+="[v$k]" }
  $concat=($filters -join ";")+";"+$labels+"concat=n=$($clips.Count):v=1:a=0[vout]"
  $ff1 = $inputs + @("-filter_complex",$concat,"-map","[vout]","-c:v","libx264","-pix_fmt","yuv420p","-y","v.mp4")
  Write-Host "Uniendo clips..." -ForegroundColor Yellow
  & ffmpeg @ff1 2>$null
  if(-not (Test-Path "v.mp4")){ Write-Host "Fallo concat" -ForegroundColor Red; exit 1 }

  # --- Stage 2: musica + voz + texto ---
  $draw = "drawtext=fontfile=fuente.ttf:textfile=caption.txt:fontcolor=yellow:fontsize=56:borderw=6:bordercolor=black:x=(w-text_w)/2:y=h-text_h-40:line_spacing=10"
  $fc = "[1:a]volume=0.22[m];[2:a]volume=1.8[vo];[m][vo]amix=inputs=2:duration=longest:normalize=0[a];[0:v]$draw[vid]"
  $ff2 = @("-i","v.mp4","-i",$music,"-i","$s\voz.mp3","-filter_complex",$fc,"-map","[vid]","-map","[a]","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-shortest","-y","$s\MEME_BIOMETRICOS.mp4")
  Write-Host "Agregando musica + voz + texto..." -ForegroundColor Yellow
  & ffmpeg @ff2 2>$null
} finally { Pop-Location }

$fin = "$s\MEME_BIOMETRICOS.mp4"
if(Test-Path $fin){
  $dst = "C:\Users\IntelGuy\Desktop\MEME_BIOMETRICOS.mp4"
  Copy-Item $fin $dst -Force
  Write-Host "LISTO -> $dst" -ForegroundColor Green
  Write-Host "dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $fin)s audio=$(ffprobe -v error -select_streams a -show_entries stream=codec_name -of csv=p=0 $fin)"
  Start-Process $dst
} else { Write-Host "NO se genero el meme" -ForegroundColor Red }

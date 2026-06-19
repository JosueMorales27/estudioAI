# ================================================================
#   ESTUDIO DE VIDEO IA LOCAL  -  100% gratis / open source
#   Clips (LTX) + Voz (edge-tts es-MX) + Subtitulos + Montaje (ffmpeg)
# ================================================================
$ErrorActionPreference = "Stop"
. "C:\AI\VideoStudio\lib.ps1"
$base = "C:\AI\VideoStudio\proyectos"

function Pausa { Write-Host ""; Read-Host "Presiona Enter para continuar" | Out-Null }

$Host.UI.RawUI.WindowTitle = "Estudio de Video IA Local"
if(-not (ComfyVivo)){
  Write-Host "ComfyUI no esta corriendo. Lo inicio..." -ForegroundColor Yellow
  Start-Process "C:\AI\ComfyUI_windows_portable\INICIAR_ComfyUI_RTX3070.bat"
  Write-Host "Esperando a que ComfyUI cargue (~1 min)..." -ForegroundColor Yellow
  for($w=0; $w -lt 80; $w++){ Start-Sleep 3; if(ComfyVivo){ break } }
}

Clear-Host
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "        ESTUDIO DE VIDEO IA LOCAL (gratis)        " -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
$proj = Read-Host "`nNombre del proyecto (ej: mi_video)"
if([string]::IsNullOrWhiteSpace($proj)){ $proj = "proyecto1" }
$pdir = Join-Path $base $proj
$clipsDir = Join-Path $pdir "clips"
$salidaDir = Join-Path $pdir "salida"
New-Item -ItemType Directory -Force $clipsDir | Out-Null
New-Item -ItemType Directory -Force $salidaDir | Out-Null
$vozMp3 = Join-Path $salidaDir "voz.mp3"
$vozSrt = Join-Path $salidaDir "voz.srt"
$finalMp4 = Join-Path $salidaDir "VIDEO_FINAL.mp4"
$W = 768; $H = 512

while($true){
  Write-Host "`n=============== PROYECTO: $proj ===============" -ForegroundColor Cyan
  $nclips = (Get-ChildItem $clipsDir -Filter *.mp4 -EA SilentlyContinue).Count
  $tv = if(Test-Path $vozMp3){"si"}else{"no"}
  Write-Host " Clips: $nclips   |   Voz: $tv   |   Resolucion: ${W}x${H}" -ForegroundColor DarkGray
  Write-Host @"

  [1] Crear un CLIP nuevo (texto en ingles, opcional imagen)
  [2] Grabar VOZ + subtitulos (dialogo en espanol)
  [3] MONTAR el video final (une clips + voz + subtitulos)
  [4] Cambiar resolucion
  [5] Abrir carpeta del proyecto
  [6] Ver/abrir clips
  [0] Salir
"@
  $op = Read-Host "Elige"
  switch($op){
    "1" {
      $pr = Read-Host "Describe el clip EN INGLES"
      Write-Host "Fotos-ancla EN ORDEN (1ra = inicio, ultima = final)." -ForegroundColor DarkGray
      Write-Host "Pega una ruta y Enter. Deja vacio y Enter para terminar. (0 fotos = solo texto)" -ForegroundColor DarkGray
      $imgs = @()
      while($true){
        $r = (Read-Host ("  Foto #" + ($imgs.Count + 1) + " (Enter=terminar)")).Trim('"')
        if([string]::IsNullOrWhiteSpace($r)){ break }
        if(Test-Path $r){ $imgs += $r } else { Write-Host "  No existe esa ruta." -ForegroundColor Red }
      }
      if($imgs.Count -ge 2){
        $seg = 0   # AUTO: mas fotos = mas largo, anclado y sin partes raras
        Write-Host ("  " + $imgs.Count + " fotos -> duracion automatica.") -ForegroundColor Green
      } else {
        $segIn = Read-Host "Duracion en segundos (Enter=3)"
        if([string]::IsNullOrWhiteSpace($segIn)){ $seg = 3 } else { $seg = [double]$segIn }
      }
      $n = "{0:D3}" -f ($nclips + 1)
      $out = Join-Path $clipsDir "clip_$n.mp4"
      Generar-Clip -Prompt $pr -Imagenes $imgs -Segundos ([double]$seg) -W $W -H $H -Pasos 30 -OutFile $out | Out-Null
      Pausa
    }
    "2" {
      Write-Host "Voces: [1] Jorge (hombre)   [2] Dalia (mujer)"
      $vsel = Read-Host "Elige voz (1/2)"
      $voz = if($vsel -eq "2"){"es-MX-DaliaNeural"}else{"es-MX-JorgeNeural"}
      Write-Host "Escribe el dialogo en espanol. Cuando termines escribe FIN y Enter:"
      $lineas = @()
      while($true){ $l = Read-Host; if($l -eq "FIN"){ break }; $lineas += $l }
      $texto = ($lineas -join " ")
      if($texto.Trim()){ Generar-Voz -Texto $texto -Voz $voz -OutMp3 $vozMp3 -OutSrt $vozSrt | Out-Null }
      Pausa
    }
    "3" {
      $clips = @(Get-ChildItem $clipsDir -Filter *.mp4 | Sort-Object Name | Select-Object -ExpandProperty FullName)
      if($clips.Count -eq 0){ Write-Host "No hay clips. Crea al menos uno." -ForegroundColor Red; Pausa; continue }
      $usarVoz = if(Test-Path $vozMp3){ $vozMp3 } else { "" }
      $usarSub = ""
      if(Test-Path $vozSrt){ if((Read-Host "Quemar subtitulos? (s/n)") -eq "s"){ $usarSub = $vozSrt } }
      Montar-Final -Clips $clips -VozMp3 $usarVoz -Srt $usarSub -OutFile $finalMp4 -W $W -H $H | Out-Null
      if(Test-Path $finalMp4){ Start-Process $finalMp4 }
      Pausa
    }
    "4" {
      $r = Read-Host "[1] 768x512 horizontal  [2] 512x768 vertical(reels)  [3] 640x640 cuadrado"
      switch($r){ "2"{$W=512;$H=768} "3"{$W=640;$H=640} default{$W=768;$H=512} }
      Write-Host "Resolucion: ${W}x${H}" -ForegroundColor Green; Pausa
    }
    "5" { Start-Process $pdir }
    "6" { Get-ChildItem $clipsDir -Filter *.mp4 | ForEach-Object { Write-Host $_.Name }; $a=Read-Host "Clip a abrir (o Enter)"; if($a){ Start-Process (Join-Path $clipsDir $a) } }
    "0" { Write-Host "Hasta luego, bro!" -ForegroundColor Cyan; exit 0 }
    default { Write-Host "Opcion invalida." -ForegroundColor Red }
  }
}

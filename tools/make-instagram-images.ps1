# Instagram用の画像を作るスクリプト（Windows用）
#
# 使い方（PowerShell を開いて、次の1行を実行）:
#   powershell -ExecutionPolicy Bypass -File tools\make-instagram-images.ps1
#
# なぜ必要か:
#   Instagramのフィード投稿は「縦横比 4:5 まで」しか受け付けません。
#   漫画は 2:3 とそれより縦長なので、そのままだと上下が切れてしまいます。
#   そこで左右に白い余白を足して 4:5 にした画像を images_ig\ に作ります。
#   （漫画そのものは一切切れません）

param(
    [string]$Source = (Join-Path $PSScriptRoot "..\images"),
    [string]$Dest   = (Join-Path $PSScriptRoot "..\images_ig"),
    [int]$OutWidth  = 1440,     # 仕上がりの横幅
    [int]$Quality   = 88
)

Add-Type -AssemblyName System.Drawing

$Source = (Resolve-Path $Source).Path
if (-not (Test-Path $Dest)) { New-Item -ItemType Directory -Path $Dest | Out-Null }
$Dest = (Resolve-Path $Dest).Path

# 4:5 = 0.8。この比率の canvas に、漫画を中央に置きます。
$ratio     = 0.8
$outHeight = [int]([math]::Round($OutWidth / $ratio))

$codec  = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq 'image/jpeg' }
$params = New-Object System.Drawing.Imaging.EncoderParameters(1)
$params.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, [long]$Quality)

$count = 0
$maxKB = 0

Get-ChildItem -Path $Source -File | Where-Object { $_.Extension -in '.jpg', '.jpeg', '.png' } | Sort-Object Name | ForEach-Object {
    $img = [System.Drawing.Image]::FromFile($_.FullName)

    # 高さいっぱいに収まるよう縮小（漫画は切らない）
    # ※ [double] を明示しないと PowerShell が整数として扱い、縮小率が 1 に丸められます
    $scaleW = [double]$OutWidth / [double]$img.Width
    $scaleH = [double]$outHeight / [double]$img.Height
    $scale  = if ($scaleW -lt $scaleH) { $scaleW } else { $scaleH }
    $drawW = [int]([math]::Round($img.Width * $scale))
    $drawH = [int]([math]::Round($img.Height * $scale))
    $offX  = [int](($OutWidth - $drawW) / 2)
    $offY  = [int](($outHeight - $drawH) / 2)

    $bmp = New-Object System.Drawing.Bitmap($OutWidth, $outHeight)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.SmoothingMode     = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $g.PixelOffsetMode   = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.Clear([System.Drawing.Color]::White)
    $g.DrawImage($img, $offX, $offY, $drawW, $drawH)

    $outPath = Join-Path $Dest ($_.BaseName + ".jpg")
    $bmp.Save($outPath, $codec, $params)

    $g.Dispose(); $bmp.Dispose(); $img.Dispose()

    $kb = [math]::Round((Get-Item $outPath).Length / 1KB, 0)
    if ($kb -gt $maxKB) { $maxKB = $kb }
    $count++
}

Write-Output ("Converted    : " + $count + " files")
Write-Output ("Canvas       : " + $OutWidth + "x" + $outHeight + " (4:5)")
Write-Output ("Largest file : " + $maxKB + " KB  (Instagram limit = 8192 KB)")
Write-Output ("Output dir   : " + $Dest)

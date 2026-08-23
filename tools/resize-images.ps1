# 漫画の画像を、Threads / X に投稿できるサイズに縮小するスクリプト（Windows用）
#
# 使い方（PowerShell を開いて、次の1行を実行）:
#   powershell -ExecutionPolicy Bypass -File tools\resize-images.ps1 -Source "C:\AI\manga"
#
# 元の画像は変更しません。images\ フォルダに .jpg として書き出します。
#
# なぜ必要か:
#   Threads は 8MB を超える画像を受け付けません。
#   スマホやAIで作った画像は 1枚 5〜10MB になることが多いので、必ず通してください。

param(
    [Parameter(Mandatory = $true)]
    [string]$Source,                                   # 元画像が入っているフォルダ

    [string]$Dest = (Join-Path $PSScriptRoot "..\images"),  # 書き出し先

    [int]$MaxWidth = 1440,                             # 横幅の上限（px）
    [int]$Quality  = 90                                # JPEG品質（90でだいたい700KB）
)

Add-Type -AssemblyName System.Drawing

$Dest = (Resolve-Path $Dest).Path

$codec  = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq 'image/jpeg' }
$params = New-Object System.Drawing.Imaging.EncoderParameters(1)
$params.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, [long]$Quality)

$count = 0
$maxKB = 0

Get-ChildItem -Path $Source -File | Where-Object { $_.Extension -in '.png', '.jpg', '.jpeg' } | Sort-Object Name | ForEach-Object {
    $img = [System.Drawing.Image]::FromFile($_.FullName)
    $w = $img.Width
    $h = $img.Height

    if ($w -gt $MaxWidth) {
        $newW = $MaxWidth
        $newH = [int]([math]::Round($h * $MaxWidth / $w))
    } else {
        $newW = $w
        $newH = $h
    }

    $bmp = New-Object System.Drawing.Bitmap($newW, $newH)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.SmoothingMode     = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $g.PixelOffsetMode   = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.Clear([System.Drawing.Color]::White)
    $g.DrawImage($img, 0, 0, $newW, $newH)

    $outPath = Join-Path $Dest ($_.BaseName + ".jpg")
    $bmp.Save($outPath, $codec, $params)

    $g.Dispose(); $bmp.Dispose(); $img.Dispose()

    $kb = [math]::Round((Get-Item $outPath).Length / 1KB, 0)
    if ($kb -gt $maxKB) { $maxKB = $kb }
    $count++

    "{0,-18} -> {1,-18} {2,5} KB  ({3}x{4})" -f $_.Name, ($_.BaseName + ".jpg"), $kb, $newW, $newH
}

Write-Output ""
Write-Output ("Converted    : " + $count + " files")
Write-Output ("Largest file : " + $maxKB + " KB  (Threads limit = 8192 KB)")
Write-Output ("Output dir   : " + $Dest)

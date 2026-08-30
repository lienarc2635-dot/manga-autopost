# note の見出し画像（アイキャッチ）を作るスクリプト（Windows用）
#
# 使い方:
#   powershell -ExecutionPolicy Bypass -File tools\make-note-eyecatch.ps1
#
# note の見出し画像は 1280x670 の横長です。
# 漫画は縦長なので、そのまま指定すると上下が切れてしまいます。
# そこで「漫画を左に、タイトルを右に」置いた専用画像を作ります。

param(
    [string]$NoteDir = (Join-Path $PSScriptRoot "..\note"),
    [string]$ImgDir  = (Join-Path $PSScriptRoot "..\images"),
    [string]$Dest    = "C:\AI\note用画像\_見出し画像"
)

Add-Type -AssemblyName System.Drawing

$W = 1280
$H = 670

$NoteDir = (Resolve-Path $NoteDir).Path
$ImgDir  = (Resolve-Path $ImgDir).Path
if (-not (Test-Path $Dest)) { New-Item -ItemType Directory -Path $Dest -Force | Out-Null }

$codec  = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq 'image/jpeg' }
$params = New-Object System.Drawing.Imaging.EncoderParameters(1)
$params.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, [long]92)

# 日本語を含む文字列を、指定した長さで折り返す
function Wrap-Text([string]$text, [int]$perLine) {
    $lines = @()
    $cur = ""
    foreach ($ch in $text.ToCharArray()) {
        $cur += $ch
        # 句読点や閉じ括弧のあとは切りやすい
        if ($cur.Length -ge $perLine) {
            $lines += $cur
            $cur = ""
        }
    }
    if ($cur.Length -gt 0) { $lines += $cur }
    return $lines
}

Get-ChildItem $NoteDir -Filter "0*.md" | Sort-Object Name | ForEach-Object {
    $raw = Get-Content $_.FullName -Raw -Encoding UTF8
    $title = (($raw -split "`r?`n")[0] -replace '^#\s*', '').Trim()

    # 本文で最初に出てくる画像を使う
    $m = [regex]::Match($raw, '〈画像：([^〉]+)〉')
    if (-not $m.Success) { return }
    $srcPath = Join-Path $ImgDir $m.Groups[1].Value
    if (-not (Test-Path $srcPath)) { return }

    $bmp = New-Object System.Drawing.Bitmap($W, $H)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode     = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit

    # 背景（ごく淡い寒色系。漫画の白と馴染むように）
    $bg = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(248, 249, 252))
    $g.FillRectangle($bg, 0, 0, $W, $H)

    # 左端に藍色の帯
    $accent = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(36, 64, 126))
    $g.FillRectangle($accent, 0, 0, 12, $H)

    # 漫画を左側に配置（高さいっぱい、切らない）
    $img = [System.Drawing.Image]::FromFile($srcPath)
    $marginY = 40
    $drawH = $H - ($marginY * 2)
    $drawW = [int]([math]::Round([double]$img.Width * $drawH / [double]$img.Height))
    $drawX = 60
    $g.DrawImage($img, $drawX, $marginY, $drawW, $drawH)
    # 漫画に薄い枠
    $pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(228, 231, 238), 1)
    $g.DrawRectangle($pen, $drawX, $marginY, $drawW, $drawH)
    $img.Dispose()

    # 右側にタイトル
    $textX = $drawX + $drawW + 56
    $textW = $W - $textX - 60

    $fontTitle = New-Object System.Drawing.Font("Yu Gothic UI", 42, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
    $fontLabel = New-Object System.Drawing.Font("Yu Gothic UI", 19, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
    $inkBrush   = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(19, 23, 32))
    $mutedBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(97, 107, 124))

    # 1行あたりの文字数を、幅から見積もる
    $perLine = [math]::Floor($textW / 43)
    $lines = Wrap-Text $title $perLine

    $lineH = 62
    $totalH = ($lines.Count * $lineH) + 60
    $startY = [int](($H - $totalH) / 2)

    $g.DrawString("3コマ漫画からのお話", $fontLabel, $mutedBrush, $textX, $startY)

    # ラベルの下に短い線
    $linePen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(195, 207, 232), 2)
    $g.DrawLine($linePen, $textX, $startY + 38, $textX + 52, $startY + 38)

    $y = $startY + 62
    foreach ($ln in $lines) {
        $g.DrawString($ln, $fontTitle, $inkBrush, $textX, $y)
        $y += $lineH
    }

    $out = Join-Path $Dest ($_.BaseName + "_見出し画像.jpg")
    $bmp.Save($out, $codec, $params)

    $g.Dispose(); $bmp.Dispose()
    "{0} … {1}行" -f (Split-Path $out -Leaf), $lines.Count
}

Write-Output ""
Write-Output ("作成先: " + $Dest)

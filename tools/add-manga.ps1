# 新しい漫画を追加するときに実行するスクリプト（Windows用）
#
# 使い方（PowerShell を開いて、次の1行を実行）:
#   powershell -ExecutionPolicy Bypass -File tools\add-manga.ps1
#
# やること:
#   1. C:\AI\manga の画像を Threads用（images\）に変換
#   2. 同じ画像を Instagram用の4:5（images_ig\）に変換
#   3. 新しく増えた画像を見つけて、posts.csv / instagram.csv に貼る雛形を表示
#   4. GitHubにアップロード（-Push を付けたときだけ）
#
# ※ 本文とキャプションは自動では書きません。表示された雛形をコピーして、
#    文章を入れてから posts.csv / instagram.csv に貼り付けてください。

param(
    [string]$Source = "C:\AI\manga",
    [switch]$Push
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

# --- 変換前に、いま何があるか記録しておく -----------------------------------
$before = @{}
Get-ChildItem -Path (Join-Path $repo "images") -Filter *.jpg -File -ErrorAction SilentlyContinue |
    ForEach-Object { $before[$_.BaseName] = $true }

# --- 1〜2. 画像を変換 --------------------------------------------------------
Write-Output "■ Threads用の画像を作っています..."
& (Join-Path $PSScriptRoot "resize-images.ps1") -Source $Source | Select-Object -Last 3

Write-Output ""
Write-Output "■ Instagram用（4:5）の画像を作っています..."
& (Join-Path $PSScriptRoot "make-instagram-images.ps1") | Select-Object -Last 3

# --- 3. 増えた画像を調べる ---------------------------------------------------
$after = Get-ChildItem -Path (Join-Path $repo "images") -Filter *.jpg -File | ForEach-Object { $_.BaseName }
$new = @($after | Where-Object { -not $before.ContainsKey($_) })

Write-Output ""
Write-Output "=========================================="
if ($new.Count -eq 0) {
    Write-Output "新しく増えた画像はありませんでした。"
    Write-Output "（既にある画像は作り直されています）"
    return
}

Write-Output ("新しく増えた画像: " + $new.Count + "枚")
Write-Output ""

# N-1 / N-2 / N-3 の形でセットにまとめる
$sets = @{}
foreach ($n in $new) {
    $parts = $n -split '-'
    if ($parts.Count -ne 2) {
        Write-Output ("  ※ " + $n + ".jpg は「27-1」のような名前ではないため、雛形に含めません")
        continue
    }
    $key = [int]$parts[0]
    if (-not $sets.ContainsKey($key)) { $sets[$key] = @() }
    $sets[$key] += [int]$parts[1]
}

# 続きの日付を決める（posts.csv の最終日の翌日から）
$posts = Import-Csv -Path (Join-Path $repo "posts.csv") -Encoding UTF8
$lastDate = ($posts | ForEach-Object { $_.PSObject.Properties.Value[0] } | Sort-Object | Select-Object -Last 1)
$next = ([datetime]::ParseExact($lastDate, 'yyyy-MM-dd', $null)).AddDays(1)

Write-Output "----- posts.csv の一番下に貼り付ける行（本文は書き換えてください）-----"
Write-Output ""
$i = 0
foreach ($key in ($sets.Keys | Sort-Object)) {
    $date = $next.AddDays($i).ToString('yyyy-MM-dd')
    foreach ($slot in ($sets[$key] | Sort-Object)) {
        Write-Output ($date + ",images/" + $key + "-" + $slot + ".jpg,ここにX本文,ここにThreads本文,")
    }
    $i++
}

Write-Output ""
Write-Output "----- instagram.csv の一番下に貼り付ける行（1日1行）-----"
Write-Output ""
$i = 0
foreach ($key in ($sets.Keys | Sort-Object)) {
    $date = $next.AddDays($i).ToString('yyyy-MM-dd')
    Write-Output ('"' + $date + '","ここにInstagramのキャプション"')
    $i++
}

Write-Output ""
Write-Output "=========================================="
Write-Output ("この分の配信予定: " + $next.ToString('yyyy-MM-dd') + " 〜 " + $next.AddDays($sets.Count - 1).ToString('yyyy-MM-dd'))

# --- 4. GitHubへアップロード -------------------------------------------------
if ($Push) {
    Write-Output ""
    Write-Output "■ GitHubにアップロードしています..."
    Push-Location $repo
    try {
        git add -A
        git commit -m ("漫画を追加（" + $new.Count + "枚）")
        git push
        Write-Output "アップロードしました。"
    } finally {
        Pop-Location
    }
} else {
    Write-Output ""
    Write-Output "※ まだGitHubには反映されていません。"
    Write-Output "  本文を書き終えたら、次を実行してアップロードしてください:"
    Write-Output "    powershell -ExecutionPolicy Bypass -File tools\add-manga.ps1 -Push"
}

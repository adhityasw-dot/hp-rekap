# Siapkan zip deploy + buka Railway
$ErrorActionPreference = "Stop"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -ErrorAction SilentlyContinue
if (-not $root) { $root = "C:\Users\Leks\Documents\hp-rekap" }
Set-Location $root

$zip = "C:\Users\Leks\Documents\hp-rekap-deploy.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }

$paths = @(
  "app", "Dockerfile", "requirements.txt", "run.py",
  "railway.toml", "render.yaml", "DEPLOY_ONLINE.md", "README.md",
  ".dockerignore", ".gitignore"
) | ForEach-Object { Join-Path $root $_ } | Where-Object { Test-Path $_ }

Compress-Archive -Path $paths -DestinationPath $zip -Force
Write-Host "ZIP siap: $zip"
Write-Host "Membuka Railway di browser..."
Start-Process "https://railway.app/new"
Start-Process "https://github.com/new"
Write-Host ""
Write-Host "Langkah singkat:"
Write-Host "1. Login Railway + GitHub (Google OK)"
Write-Host "2. Buat repo GitHub, upload isi folder hp-rekap (atau zip)"
Write-Host "3. Railway: New Project -> Deploy from GitHub"
Write-Host "4. Set Variables + Volume /data (lihat DEPLOY_ONLINE.md)"
Write-Host "5. Generate Domain, buka URL, login, Import spreadsheet"

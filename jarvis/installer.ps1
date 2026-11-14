# installer.ps1 — Installation de Jarvis sur Windows 10/11.
#
# Lancer depuis le dossier jarvis, dans PowerShell (pas besoin d'administrateur) :
#   powershell -ExecutionPolicy Bypass -File .\installer.ps1
#
# Variables facultatives :
#   $env:JARVIS_MODELE_LOCAL = "qwen3:8b"   # pour forcer un autre modèle local

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Step($text) { Write-Host "`n== $text ==" -ForegroundColor Cyan }

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Install-WithWinget($id, $command) {
    if (Get-Command $command -ErrorAction SilentlyContinue) {
        Write-Host "  $command : déjà installé"
        return
    }
    Write-Host "  Installation de $id..."
    winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command introuvable après installation. Ferme et rouvre PowerShell, puis relance le script."
    }
}

# Choix du modèle local selon la mémoire vive.
function Pick-Model {
    if ($env:JARVIS_MODELE_LOCAL) { return @{ Model = $env:JARVIS_MODELE_LOCAL; Think = "" } }
    $ramGo = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    Write-Host "  Mémoire vive détectée : $ramGo Go"
    if ($ramGo -ge 48) { return @{ Model = "qwen3:30b-a3b"; Think = "0" } }   # gros modèle, rapide (MoE)
    if ($ramGo -ge 24) { return @{ Model = "mistral-small3.2"; Think = "" } }
    return @{ Model = "qwen3:8b"; Think = "0" }
}

# Écrit une ligne CLE=valeur dans .env (UTF-8 sans BOM, lisible par Python).
function Set-EnvLine($key, $value) {
    $path = Join-Path $PSScriptRoot ".env"
    $lines = [System.IO.File]::ReadAllLines($path)
    $found = $false
    $out = @(foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($key))=") { $found = $true; "$key=$value" } else { $line }
    })
    if (-not $found) { $out += "$key=$value" }
    [System.IO.File]::WriteAllLines($path, [string[]]$out, (New-Object System.Text.UTF8Encoding($false)))
}

Step "1/7 Vérification de winget"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget est absent. Installe « App Installer » depuis le Microsoft Store, puis relance."
}

Step "2/7 Python, Ollama, ffmpeg et Git"
Install-WithWinget "Python.Python.3.12" "py"
Install-WithWinget "Ollama.Ollama" "ollama"
Install-WithWinget "Gyan.FFmpeg" "ffmpeg"
Install-WithWinget "Git.Git" "git"

Step "3/7 Environnement Python"
if (-not (Test-Path ".venv")) { py -3.12 -m venv .venv }
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $python -m pip install --upgrade pip --quiet
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "L'installation des dépendances Python a échoué." }

Step "4/7 Voix française (Piper)"
New-Item -ItemType Directory -Force -Path "voix" | Out-Null
$base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR"
foreach ($v in @("tom", "siwis")) {  # tom = voix d'homme (défaut), siwis = voix de femme
    foreach ($f in @("fr_FR-$v-medium.onnx", "fr_FR-$v-medium.onnx.json")) {
        $dest = Join-Path "voix" $f
        if (-not (Test-Path $dest)) { Invoke-WebRequest -Uri "$base/$v/medium/$f" -OutFile $dest -UseBasicParsing }
    }
}

Step "5/7 Configuration (.env)"
$choice = Pick-Model
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Set-EnvLine "JARVIS_MODELE_LOCAL" $choice.Model
    Set-EnvLine "JARVIS_REFLEXION_LOCALE" $choice.Think
    Write-Host "  .env créé avec le modèle $($choice.Model)"
} else {
    Write-Host "  .env existe déjà : je n'y touche pas."
    $line = Select-String -Path ".env" -Pattern "^JARVIS_MODELE_LOCAL=(.+)$" | Select-Object -First 1
    if ($line) { $choice.Model = $line.Matches[0].Groups[1].Value.Trim() }
}

Step "6/7 Modèle local ($($choice.Model)) — plusieurs Go, patience"
if (-not (Get-Process -Name "ollama*" -ErrorAction SilentlyContinue)) {
    Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
}
ollama pull $choice.Model
if ($LASTEXITCODE -ne 0) { throw "Le téléchargement du modèle a échoué." }

Step "7/7 Préchargement de Whisper (reconnaissance vocale)"
& $python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

Write-Host ""
if (Get-Command claude -ErrorAction SilentlyContinue) {
    Write-Host "✅ Claude Code est installé : le renfort passera par ton abonnement." -ForegroundColor Green
    Write-Host "   Si ce n'est pas déjà fait, lance « claude » une fois et connecte-toi."
} else {
    Write-Host "ℹ️  Pour le renfort Claude via ton abonnement :"
    Write-Host "   irm https://claude.ai/install.ps1 | iex   puis lance « claude » une fois pour te connecter."
}
Write-Host ""
Write-Host "✅ Jarvis est installé. Pour le lancer :" -ForegroundColor Green
Write-Host "   .venv\Scripts\python.exe main.py          # au clavier"
Write-Host "   .venv\Scripts\python.exe main.py --mains-libres   # à la voix, sans clavier : dis « Jarvis »"
Write-Host "   .venv\Scripts\python.exe telegram_bot.py  # sur Telegram (depuis ton téléphone)"
Write-Host "   .venv\Scripts\python.exe signal_bot.py    # sur Signal (plus privé ; voir signal_notify.py pour relier signal-cli)"
Write-Host ""
Write-Host "Ensuite, pour optimiser le PC (en administrateur) : .\optimiser_windows.ps1"

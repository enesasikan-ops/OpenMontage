# optimiser_windows.ps1 — Optimise un PC Windows pour faire tourner Jarvis 24h/24.
#
# À lancer APRÈS installer.ps1, dans PowerShell ouvert « en tant qu'administrateur » :
#   powershell -ExecutionPolicy Bypass -File .\optimiser_windows.ps1
#
# Chaque réglage est expliqué et demande ton accord (O/N). Rien n'est fait sans « O ».
# Pour tout annuler plus tard : .\optimiser_windows.ps1 -Annuler

param([switch]$Annuler)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw "Lance PowerShell « en tant qu'administrateur » (clic droit sur PowerShell), puis relance ce script."
}

$TaskName = "Jarvis Telegram"
$WuKey = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
$OllamaVars = [ordered]@{
    "OLLAMA_KEEP_ALIVE"      = "-1"     # garde le modèle en mémoire : pas d'attente au réveil
    "OLLAMA_FLASH_ATTENTION" = "1"      # calcul plus rapide et plus économe en mémoire
    "OLLAMA_KV_CACHE_TYPE"   = "q8_0"   # mémoire de conversation compressée (qualité quasi identique)
    "OLLAMA_CONTEXT_LENGTH"  = "8192"   # longueur de conversation suffisante pour un assistant
    "OLLAMA_VULKAN"          = "1"      # utilise la puce graphique AMD (Radeon 780M) si Ollama le permet
}

function Ask($question) {
    $answer = Read-Host "$question (O/N)"
    return $answer -match "^(o|oui|y|yes)$"
}

function Restart-Ollama {
    Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
    $app = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
    if (Test-Path $app) { Start-Process $app } else { Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden }
}

if ($Annuler) {
    Write-Host "Annulation des réglages Jarvis..." -ForegroundColor Yellow
    powercfg /setactive SCHEME_BALANCED
    powercfg /change standby-timeout-ac 30
    foreach ($name in $OllamaVars.Keys) { [Environment]::SetEnvironmentVariable($name, $null, "User") }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path $WuKey -Name "NoAutoRebootWithLoggedOnUsers" -ErrorAction SilentlyContinue
    Restart-Ollama
    Write-Host "✅ Réglages d'origine rétablis." -ForegroundColor Green
    return
}

Write-Host "Optimisation du PC pour Jarvis. Réponds O (oui) ou N (non) à chaque étape.`n" -ForegroundColor Cyan

# 1. Énergie --------------------------------------------------------------------
Write-Host "1) ÉNERGIE : mode « performances élevées », et le PC ne se met plus en veille"
Write-Host "   (l'écran, lui, peut toujours s'éteindre). Indispensable pour un assistant 24h/24."
if (Ask "   Appliquer ?") {
    powercfg /setactive SCHEME_MIN
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    powercfg /change monitor-timeout-ac 10
    Write-Host "   ✅ Fait." -ForegroundColor Green
}

# 2. Ollama -----------------------------------------------------------------------
Write-Host "`n2) OLLAMA : réglages de vitesse pour le modèle local :"
foreach ($name in $OllamaVars.Keys) { Write-Host "     $name = $($OllamaVars[$name])" }
Write-Host "   Le modèle reste chargé en mémoire en permanence : réponses immédiates,"
Write-Host "   mais cette mémoire (≈ 20 Go pour qwen3:30b-a3b) n'est plus libre pour autre chose."
if (Ask "   Appliquer ?") {
    foreach ($name in $OllamaVars.Keys) {
        [Environment]::SetEnvironmentVariable($name, $OllamaVars[$name], "User")
    }
    Restart-Ollama
    Write-Host "   ✅ Fait. Ollama a redémarré avec les nouveaux réglages." -ForegroundColor Green
}

# 3. Démarrage automatique du bot Telegram ---------------------------------------
$pythonw = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
Write-Host "`n3) DÉMARRAGE AUTOMATIQUE : le bot Telegram se lance tout seul (sans fenêtre)"
Write-Host "   à l'ouverture de ta session Windows, et redémarre s'il plante."
Write-Host "   Journal : $env:USERPROFILE\.jarvis\telegram_bot.log"
if (-not (Test-Path $pythonw)) {
    Write-Host "   ⚠️ Lance d'abord installer.ps1 (pythonw.exe introuvable)." -ForegroundColor Yellow
} elseif (Ask "   Appliquer ?") {
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument "telegram_bot.py" -WorkingDirectory $PSScriptRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $trigger.Delay = "PT30S"  # laisse 30 s à Ollama pour démarrer
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Description "Jarvis : assistant personnel sur Telegram" -Force | Out-Null
    Write-Host "   ✅ Fait. Pour le lancer tout de suite : Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Green
}

# 4. Windows Update ---------------------------------------------------------------
Write-Host "`n4) WINDOWS UPDATE : les mises à jour continuent, mais Windows ne redémarre plus"
Write-Host "   tout seul quand ta session est ouverte (sinon Jarvis s'arrête la nuit)."
Write-Host "   Pense à redémarrer toi-même de temps en temps pour finir les mises à jour."
if (Ask "   Appliquer ?") {
    New-Item -Path $WuKey -Force | Out-Null
    Set-ItemProperty -Path $WuKey -Name "NoAutoRebootWithLoggedOnUsers" -Value 1 -Type DWord
    Write-Host "   ✅ Fait." -ForegroundColor Green
}

# 5. Ce qui se règle à la main --------------------------------------------------------
Write-Host "`n5) À FAIRE À LA MAIN (je ne le fais pas automatiquement) :" -ForegroundColor Cyan
Write-Host "   • BIOS : touche Suppr ou F2 au démarrage → « UMA Frame Buffer Size » sur 16G"
Write-Host "     (mémoire réservée à la puce graphique, pour qu'Ollama puisse s'en servir)."
Write-Host "   • Ouverture de session automatique (pour que Jarvis redémarre seul après une"
Write-Host "     coupure de courant) : touche Windows + R → netplwiz. Pratique, mais toute"
Write-Host "     personne qui allume le PC arrive sur ta session : à toi de voir."
Write-Host "   • Vérifier que la puce graphique est utilisée : « ollama ps » pendant que Jarvis"
Write-Host "     répond. « GPU » = parfait ; « CPU » = ça marche, mais un peu plus lentement."
Write-Host "`n6) BANC D'ESSAI : une fois Ollama redémarré (et le BIOS réglé), mesure la"
Write-Host "   configuration la plus rapide sur CE PC (quelques minutes, sans rien casser) :"
Write-Host "     .venv\Scripts\python.exe bench.py --appliquer"
Write-Host "`n✅ Optimisation terminée. Annuler tout : .\optimiser_windows.ps1 -Annuler" -ForegroundColor Green

# Registra (ou remove) a tarefa que coleta os feeds de URL a cada 12h.
#
# O OpenPhish só publica as URLs ativas nas últimas ~12h, então o corpus de
# phishing só cresce se a coleta rodar de forma recorrente. A tarefa roda sob a
# conta do usuário logado, sem privilégio elevado.
#
#   .\scripts\agendar_coleta.ps1              # registra
#   .\scripts\agendar_coleta.ps1 -Remover     # remove
#   .\scripts\agendar_coleta.ps1 -Status      # consulta

param(
    [switch]$Remover,
    [switch]$Status
)

$nome = "PhishGuardBR-ColetaURL"
$cmd = Join-Path $PSScriptRoot "coletar_feeds.cmd"

if ($Status) {
    schtasks /Query /TN $nome /V /FO LIST
    exit $LASTEXITCODE
}

if ($Remover) {
    schtasks /Delete /TN $nome /F
    exit $LASTEXITCODE
}

if (-not (Test-Path $cmd)) {
    Write-Error "Nao encontrei $cmd"
    exit 1
}

# /MO 12 com /SC HOURLY = a cada 12 horas. /F sobrescreve se ja existir.
schtasks /Create /TN $nome /TR "`"$cmd`"" /SC HOURLY /MO 12 /ST 08:00 /F
if ($?) {
    Write-Host "Tarefa '$nome' registrada: roda a cada 12h."
    Write-Host "Log: ml\data\raw\url_feeds\coleta.log"
}

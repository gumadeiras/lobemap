$ErrorActionPreference = 'Stop'
foreach ($v in 'NEUPRINT_APPLICATION_CREDENTIALS', 'FLYWIRE_APPLICATION_CREDENTIALS') {
    $val = [Environment]::GetEnvironmentVariable($v, 'User')
    if ($val) { Set-Item -Path "Env:$v" -Value $val }
}
$userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
if ($userPath) { $env:PATH = $env:PATH + ';' + $userPath }
# The script's own directory IS the checkout, so this follows it rather
# than hard-coding one developer's path.
Set-Location $PSScriptRoot
& '.venv\Scripts\python.exe' -u -m lobemap.cli @args

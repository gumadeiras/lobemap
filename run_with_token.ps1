# Bridges User-scope environment (tokens + PATH) into this process only.
# Nothing here echoes a secret value.
$ErrorActionPreference = 'Stop'
foreach ($v in 'NEUPRINT_APPLICATION_CREDENTIALS', 'FLYWIRE_APPLICATION_CREDENTIALS') {
    $val = [Environment]::GetEnvironmentVariable($v, 'User')
    if ($val) { Set-Item -Path "Env:$v" -Value $val }
}
# CMTK lives on the User PATH; a process started before it was added will not
# have inherited it.
$userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
if ($userPath) { $env:PATH = $env:PATH + ';' + $userPath }
# Resolved from the script's own location, so moving or renaming the
# checkout cannot break it; it used to hard-code one developer's path.
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -m lobemap.cli @args

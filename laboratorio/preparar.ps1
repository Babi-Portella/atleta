param(
    [ValidateSet('local', 'server')]
    [string]$Perfil = 'local',
    [switch]$Iniciar
)
$ErrorActionPreference = 'Stop'
$taskLabDir = $PSScriptRoot
$taskVenvDir = Join-Path (Split-Path $taskLabDir -Parent) '.venv-lab'
$taskPython = Join-Path $taskVenvDir 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & python -m venv $taskVenvDir
    if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel criar o ambiente Python.' }
}
& $taskPython -m pip install --disable-pip-version-check -r (Join-Path $taskLabDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependencias.' }
& $taskPython (Join-Path $taskLabDir 'tools\lab.py') init --profile $Perfil
if ($LASTEXITCODE -ne 0) { throw 'Falha na preparacao do laboratorio.' }
if ($Iniciar) {
    & $taskPython (Join-Path $taskLabDir 'tools\lab.py') up
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao iniciar. Confira o Docker e as portas.' }
}

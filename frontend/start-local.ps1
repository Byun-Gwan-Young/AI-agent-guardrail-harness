param([string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonPath) {
    $candidate = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $candidate) { $PythonPath = $candidate }
}
if (-not $PythonPath) {
    $desktopPath = [Environment]::GetFolderPath('Desktop')
    $candidate = Join-Path $desktopPath '캡스톤\코도 실습\AI-agent-guardrail-harness-main\AI-agent-guardrail-harness-main\.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $candidate) { $PythonPath = $candidate }
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath)) {
    throw 'Create a repo .venv and install service/requirements-server.txt, or pass -PythonPath with an existing project Python.'
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'node_modules\vite\bin\vite.js'))) { throw 'Run npm install in frontend first.' }
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$postgresBin = 'C:\Program Files\PostgreSQL\18\bin'
if (Test-Path -LiteralPath $postgresBin) { $env:PATH = $postgresBin + ';' + $env:PATH }
Write-Host 'Uses the existing LOCAL guardrail_local_pc database. No DB initialization or import is performed.'
Write-Host 'Google authorized origins: http://localhost and http://localhost:5173'
Write-Host 'Google redirect URI: http://localhost:5173/api/auth/google'
$env:VITE_GOOGLE_CLIENT_ID = (Read-Host 'Google OAuth WEB client ID').Trim()
if (-not $env:VITE_GOOGLE_CLIENT_ID.EndsWith('.apps.googleusercontent.com')) { throw 'Invalid web client ID.' }
$env:GOOGLE_CLIENT_ID = $env:VITE_GOOGLE_CLIENT_ID
$env:GOOGLE_LOGIN_URI = 'http://localhost:5173/api/auth/google'
$env:AUTH_COOKIE_SECURE = 'false'
$env:API_PROXY_TARGET = 'http://127.0.0.1:8040'
$portText = Read-Host 'LOCAL PostgreSQL port (Enter = 5432)'
$dbPort = if ($portText) { [int]$portText } else { 5432 }
if ($dbPort -lt 1 -or $dbPort -gt 65535) { throw 'Invalid DB port.' }
$dbUser = Read-Host 'LOCAL PostgreSQL username (Enter = postgres)'
$env:PGUSER = if ($dbUser) { $dbUser } else { 'postgres' }
$env:PGHOST = '127.0.0.1'
$env:PGPORT = [string]$dbPort
$env:PGCONNECT_TIMEOUT = '5'
$env:GUARDRAIL_DB_URL = "host=127.0.0.1 port=$dbPort dbname=guardrail_local_pc connect_timeout=5"
$password = Read-Host 'LOCAL PostgreSQL password (hidden)' -AsSecureString
$passwordPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
$adapter = $null
try {
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPtr)
    & $PythonPath -B (Join-Path $PSScriptRoot 'check_database.py')
    if ($LASTEXITCODE -ne 0) { throw 'Database check failed; the server was not started.' }
    # Fail on port conflicts; never terminate another user's existing local server.
    foreach ($port in @(5173,8040)) {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $port)
        try { $listener.Start() } catch { throw "Port $port is already in use. Close that server or use a different configuration." } finally { $listener.Stop() }
    }
    $logDir = Join-Path $PSScriptRoot '.local-logs'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $adapterArgs = @('-B', ('"{0}"' -f (Join-Path $PSScriptRoot 'dev_server.py')))
    $adapter = Start-Process -FilePath $PythonPath -ArgumentList $adapterArgs -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'adapter.log') -RedirectStandardError (Join-Path $logDir 'adapter-error.log')
    Start-Sleep -Seconds 2
    if ($adapter.HasExited) { throw 'Local API adapter stopped. See frontend/.local-logs/adapter-error.log.' }
    Write-Host 'Open http://localhost:5173/login in a browser. Ctrl+C stops these local servers.'
    Push-Location -LiteralPath $PSScriptRoot
    try { & node.exe (Join-Path $PSScriptRoot 'node_modules\vite\bin\vite.js') } finally { Pop-Location }
} finally {
    if ($adapter -and -not $adapter.HasExited) { Stop-Process -Id $adapter.Id -ErrorAction SilentlyContinue }
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPtr)
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    $password.Dispose()
}

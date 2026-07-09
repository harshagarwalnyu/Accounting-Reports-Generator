function Get-FreePort {
    $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $l.Start()
    $port = $l.LocalEndpoint.Port
    $l.Stop()
    return $port
}

$env:FRONTEND_PORT = Get-FreePort
$env:BACKEND_PORT  = Get-FreePort

Write-Host "frontend -> http://localhost:$env:FRONTEND_PORT"
Write-Host "backend  -> http://localhost:$env:BACKEND_PORT"

docker compose up --build @args

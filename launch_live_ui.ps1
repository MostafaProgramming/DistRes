$ErrorActionPreference = "Stop"

# Build the C++ server/client so the live UI uses the latest DistRes code.
powershell -ExecutionPolicy Bypass -File .\build.ps1

function Start-DistResProcess {
    param([string] $FileName)

    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $FileName
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $info
    [void] $process.Start()
    return $process
}

# Start the C++ DistRes server as the real backend for browser users.
$server = Start-DistResProcess ".\DistResServer.exe"
Start-Sleep -Seconds 1

try {
    Write-Host "Opening live DistRes UI at http://localhost:8200"
    Write-Host "Press Ctrl+C to stop the live UI and server."

    # The Python bridge serves the browser UI and translates HTTP calls into
    # the existing DistRes TCP protocol.
    python .\live_ui_server.py
}
finally {
    if (!$server.HasExited) {
        $server.Kill()
    }
}

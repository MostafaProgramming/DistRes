$ErrorActionPreference = "Stop"

# Always rebuild first so the demonstration uses the latest source code.
powershell -ExecutionPolicy Bypass -File .\build.ps1

# Runtime evidence is written here for the implementation report and visualiser.
New-Item -ItemType Directory -Force -Path ".\logs" | Out-Null

function Start-DistResProcess {
    param(
        [string] $FileName,
        [string] $Arguments = "",
        [string] $LogName
    )

    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $FileName
    $info.Arguments = $Arguments

    # Use direct process control so the demo can run quietly and capture output.
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $info
    $process.EnableRaisingEvents = $false
    $process | Add-Member -NotePropertyName LogName -NotePropertyValue $LogName
    [void] $process.Start()
    return $process
}

function Save-DistResLog {
    param([System.Diagnostics.Process] $Process)

    if ($Process.LogName -eq "") {
        return
    }

    $stdout = Join-Path ".\logs" "$($Process.LogName).out.txt"
    $stderr = Join-Path ".\logs" "$($Process.LogName).err.txt"

    # These logs prove what each distributed client observed during the run.
    $Process.StandardOutput.ReadToEnd() | Set-Content -LiteralPath $stdout
    $Process.StandardError.ReadToEnd() | Set-Content -LiteralPath $stderr
}

# Start the server first because every client connects to this socket endpoint.
$server = Start-DistResProcess ".\DistResServer.exe" "" "server"
Start-Sleep -Seconds 1

try {
    $clients = @()

    # Launch four independent client processes to demonstrate distributed nodes.
    $clients += Start-DistResProcess ".\DistResClient.exe" "alice pass1 --auto" "client-alice"
    $clients += Start-DistResProcess ".\DistResClient.exe" "ben pass2 --auto" "client-ben"
    $clients += Start-DistResProcess ".\DistResClient.exe" "chen pass3 --auto" "client-chen"
    $clients += Start-DistResProcess ".\DistResClient.exe" "dina pass4 --auto" "client-dina"

    foreach ($client in $clients) {
        $client.WaitForExit()
        Save-DistResLog $client
    }
}
finally {
    # The server runs forever by design, so the demo stops it after clients finish.
    if (!$server.HasExited) {
        $server.Kill()
        $server.WaitForExit()
    }
    Save-DistResLog $server
}

Write-Host "Demo complete. Evidence logs are in .\logs"

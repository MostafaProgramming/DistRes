$ErrorActionPreference = "Stop"

# Produce fresh runtime evidence first: compile, start server, run four clients,
# and capture their output under .\logs.
powershell -ExecutionPolicy Bypass -File .\run_demo.ps1

# Convert the demo logs into frontend/data/distres_run.json for replay mode.
python .\generate_frontend_data.py

Write-Host "Opening DistRes dashboard at http://localhost:8100"

# This process stays running so the browser can load the dashboard and API.
python .\frontend_server.py

$ErrorActionPreference = "Stop"

# Build the server node. -lws2_32 links the Windows Winsock library used for TCP sockets.
g++ -std=c++20 -Wall -Wextra -O2 DistResServer.cpp -lws2_32 -o DistResServer.exe

# Build the client node. The same executable is launched multiple times to represent
# separate distributed client nodes in the demo.
g++ -std=c++20 -Wall -Wextra -O2 DistResClient.cpp -lws2_32 -o DistResClient.exe

Write-Host "Built DistResServer.exe and DistResClient.exe"

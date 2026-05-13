#include "DistResCommon.h"

SOCKET connectWithRetry(int attempts, int delayMs)
{
    // DistRes clients may start before the server; retrying models basic fault tolerance.
    for (int attempt = 1; attempt <= attempts; ++attempt) {
        SOCKET socketHandle = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        if (socketHandle == INVALID_SOCKET)
            return INVALID_SOCKET;

        // All clients connect to the same server socket endpoint.
        sockaddr_in server{};
        server.sin_family = AF_INET;
        server.sin_port = htons(DistResPort);
        inet_pton(AF_INET, DistResHost, &server.sin_addr);

        // A successful connection returns the active request-channel socket.
        if (connect(socketHandle, reinterpret_cast<sockaddr*>(&server), sizeof(server)) != SOCKET_ERROR)
            return socketHandle;

        // Close failed sockets before retrying so resources are not leaked.
        closesocket(socketHandle);
        std::cout << "[" << nowTime() << "] Server unavailable, retry "
                  << attempt << "/" << attempts << "\n";
        std::this_thread::sleep_for(std::chrono::milliseconds(delayMs));
    }

    return INVALID_SOCKET;
}

bool authenticate(SOCKET socket, const std::string& username, const std::string& password)
{
    std::string response;
    // The server must approve credentials before the client can read or write.
    sendLine(socket, "AUTH " + username + " " + password);
    return recvLine(socket, response) && response == "OK AUTH";
}

void subscriberLoop(std::string username, std::string password)
{
    // A separate socket is kept open so update notifications can arrive while
    // the main command socket continues sending READ and WRITE requests.
    SOCKET sub = connectWithRetry(8, 500);
    if (sub == INVALID_SOCKET || !authenticate(sub, username, password))
        return;

    // SUBSCRIBE registers this socket with the server-side PubSubBroker.
    sendLine(sub, "SUBSCRIBE");
    std::string line;
    if (recvLine(sub, line))
        std::cout << "[" << nowTime() << "] subscription: " << line << "\n";

    while (recvLine(sub, line))
        std::cout << "[" << nowTime() << "] notification: " << line << "\n";

    closesocket(sub);
}

void runAutoDemo(SOCKET commandSocket, const std::string& username)
{
    // Automatic mode gives repeatable demonstration evidence: read once,
    // perform a write, then read again to show the server-hosted file changed.
    std::string response;

    // First request proves the client can query the distributed resource.
    sendLine(commandSocket, "READ");
    if (recvLine(commandSocket, response))
        std::cout << "[" << nowTime() << "] " << username << " received " << response << "\n";

    std::this_thread::sleep_for(std::chrono::milliseconds(250));

    // The write request is sent to the server; the client never opens the file.
    sendLine(commandSocket, "WRITE distributed-update-from-" + username);
    if (recvLine(commandSocket, response))
        std::cout << "[" << nowTime() << "] " << username << " received " << response << "\n";

    std::this_thread::sleep_for(std::chrono::milliseconds(250));

    // Final read confirms that the server accepted and stored the update.
    sendLine(commandSocket, "READ");
    if (recvLine(commandSocket, response))
        std::cout << "[" << nowTime() << "] " << username << " received " << response << "\n";
}

void runInteractive(SOCKET commandSocket)
{
    // Interactive mode is useful for a live demo because the user can type
    // read/write commands and immediately see the server response.
    std::cout << "Commands: read | write <text> | quit\n";

    std::string input;
    std::string response;
    while (std::getline(std::cin, input)) {
        if (input == "read") {
            // Convert a friendly console command into the protocol command.
            sendLine(commandSocket, "READ");
        } else if (input.rfind("write ", 0) == 0) {
            // User text is sanitised so it stays inside one protocol line.
            sendLine(commandSocket, "WRITE " + sanitiseSingleLine(input.substr(6)));
        } else if (input == "quit") {
            sendLine(commandSocket, "QUIT");
            break;
        } else {
            std::cout << "Unknown command.\n";
            continue;
        }

        if (recvLine(commandSocket, response))
            std::cout << response << "\n";
    }
}

int main(int argc, char** argv)
{
    // The client needs credentials because the server authenticates every node.
    if (argc < 3) {
        std::cout << "Usage: DistResClient.exe <username> <password> [--auto]\n";
        return 1;
    }

    WinsockSession winsock;
    if (!winsock.ok()) {
        std::cerr << "Failed to initialise Winsock.\n";
        return 1;
    }

    std::string username = argv[1];
    std::string password = argv[2];

    // --auto is used by run_demo.ps1 to launch multiple repeatable clients.
    bool autoMode = argc >= 4 && std::string(argv[3]) == "--auto";

    // The command socket carries AUTH, READ, WRITE, and QUIT requests.
    SOCKET commandSocket = connectWithRetry(8, 500);
    if (commandSocket == INVALID_SOCKET) {
        std::cerr << "Could not connect to DistRes server.\n";
        return 1;
    }

    if (!authenticate(commandSocket, username, password)) {
        std::cerr << "Authentication failed for " << username << ".\n";
        closesocket(commandSocket);
        return 1;
    }

    // A second socket listens for publish-subscribe notifications in parallel.
    std::thread subscriber(subscriberLoop, username, password);
    subscriber.detach();

    if (autoMode)
        runAutoDemo(commandSocket, username);
    else
        runInteractive(commandSocket);

    sendLine(commandSocket, "QUIT");
    closesocket(commandSocket);
    // Give the detached subscriber thread a short moment to print final events.
    std::this_thread::sleep_for(std::chrono::milliseconds(500));
}

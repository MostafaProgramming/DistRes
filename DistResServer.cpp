#include "DistResCommon.h"

struct UserRecord {
    std::string username;
    std::string password;
};

// Server-side credential store. In the coursework scenario, credentials are
// hosted by the server node, so clients must authenticate before resource use.
class UserStore {
public:
    UserStore()
        : users_{
            {"alice", "pass1"},
            {"ben", "pass2"},
            {"chen", "pass3"},
            {"dina", "pass4"},
            {"emma", "pass5"}
        }
    {
    }

    bool authenticate(const std::string& username, const std::string& password) const
    {
        return std::any_of(users_.begin(), users_.end(), [&](const UserRecord& user) {
            return user.username == username && user.password == password;
        });
    }

private:
    std::vector<UserRecord> users_;
};

// Server-side data access layer for ProductSpecification.txt.
// This class is the only place that reads from or writes to the shared file.
class ResourceRepository {
public:
    explicit ResourceRepository(std::string path)
        : path_(std::move(path))
    {
        ensureFileExists();
    }

    std::string readAll(const std::string& username)
    {
        // ReadGuard acquires shared access and releases it automatically when
        // the function returns, allowing multiple readers but no writer.
        ReadGuard guard(lock_);
        std::ifstream input(path_);
        std::ostringstream buffer;
        buffer << input.rdbuf();

        std::lock_guard<std::mutex> out(outputMutex_);
        std::cout << "[" << nowTime() << "] READ granted to " << username << "\n";
        return sanitiseSingleLine(buffer.str());
    }

    int appendUpdate(const std::string& username, const std::string& text)
    {
        // WriteGuard gives this client exclusive access to the shared file.
        WriteGuard guard(lock_);

        // Version numbers make write acknowledgements and notifications traceable.
        int version = ++version_;
        std::ofstream output(path_, std::ios::app);
        output << "[" << nowTime() << "] " << username << ": " << text << "\n";

        std::lock_guard<std::mutex> out(outputMutex_);
        std::cout << "[" << nowTime() << "] WRITE v" << version
                  << " committed by " << username << "\n";
        return version;
    }

private:
    void ensureFileExists()
    {
        std::ifstream existing(path_);
        if (existing.good())
            return;

        std::ofstream output(path_);
        output << "DistRes shared ProductSpecification.txt\n";
        output << "Server-hosted resource for distributed read/write access.\n";
    }

    std::string path_;
    WriterFairRWLock lock_;
    int version_ = 0;
    std::mutex outputMutex_;
};

// Publish-subscribe broker for distributed update notifications.
// Clients register a subscription socket, then the broker broadcasts an event
// whenever a write is successfully committed to the shared resource.
class PubSubBroker {
public:
    void add(SOCKET socket)
    {
        std::lock_guard<std::mutex> lock(mutex_);
        subscribers_.push_back(socket);
    }

    void remove(SOCKET socket)
    {
        std::lock_guard<std::mutex> lock(mutex_);
        subscribers_.erase(
            std::remove(subscribers_.begin(), subscribers_.end(), socket),
            subscribers_.end()
        );
    }

    void publish(int version, const std::string& username, const std::string& text)
    {
        std::lock_guard<std::mutex> lock(mutex_);
        // Subscribers only receive events after the write has been committed.
        std::string event = "EVENT UPDATE v" + std::to_string(version)
            + " writer=" + username + " text=" + sanitiseSingleLine(text);

        for (auto it = subscribers_.begin(); it != subscribers_.end();) {
            if (sendLine(*it, event)) {
                ++it;
            } else {
                // Failed subscribers are removed so one dead client does not
                // block future notifications to healthy clients.
                closesocket(*it);
                it = subscribers_.erase(it);
            }
        }
    }

private:
    std::mutex mutex_;
    std::vector<SOCKET> subscribers_;
};

// Main server node. It listens for client sockets, authenticates users, routes
// protocol commands, coordinates access to the shared file, and publishes
// notifications to subscribed clients.
class DistResServer {
public:
    DistResServer()
        : resource_("ProductSpecification.txt")
    {
    }

    bool start()
    {
        // Create the listening socket that represents the server endpoint.
        listenSocket_ = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        if (listenSocket_ == INVALID_SOCKET)
            return false;

        // Bind to all local interfaces on the DistRes coursework port.
        sockaddr_in address{};
        address.sin_family = AF_INET;
        address.sin_addr.s_addr = INADDR_ANY;
        address.sin_port = htons(DistResPort);

        // bind() reserves the port; listen() marks it ready for TCP clients.
        if (bind(listenSocket_, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == SOCKET_ERROR)
            return false;
        if (listen(listenSocket_, SOMAXCONN) == SOCKET_ERROR)
            return false;

        std::cout << "DistRes server listening on port " << DistResPort << "\n";
        return true;
    }

    void run()
    {
        // The server stays alive and accepts client nodes until stopped.
        while (true) {
            SOCKET client = accept(listenSocket_, nullptr, nullptr);
            if (client == INVALID_SOCKET)
                continue;

            // Each accepted client is handled independently, so several nodes
            // can interact with the server at the same time.
            std::thread(&DistResServer::handleClient, this, client).detach();
        }
    }

private:
    void handleClient(SOCKET client)
    {
        std::string username;
        if (!authenticateClient(client, username)) {
            closesocket(client);
            return;
        }

        std::string line;
        while (recvLine(client, line)) {
            if (line == "READ") {
                // The server performs the read through ResourceRepository so
                // clients never touch ProductSpecification.txt directly.
                sendLine(client, "DATA " + resource_.readAll(username));
            } else if (line.rfind("WRITE ", 0) == 0) {
                std::string text = line.substr(6);

                // appendUpdate handles exclusive access and returns a committed version.
                int version = resource_.appendUpdate(username, text);
                sendLine(client, "OK WRITE v" + std::to_string(version));

                // Publish after acknowledgement data exists and the file update is durable.
                broker_.publish(version, username, text);
            } else if (line == "SUBSCRIBE") {
                // This socket becomes a long-lived observer for update events.
                broker_.add(client);
                sendLine(client, "OK SUBSCRIBED");
                keepSubscriberOpen(client);
                return;
            } else if (line == "QUIT") {
                sendLine(client, "OK BYE");
                break;
            } else {
                sendLine(client, "ERR Unknown command");
            }
        }

        closesocket(client);
    }

    bool authenticateClient(SOCKET client, std::string& username)
    {
        std::string line;
        if (!recvLine(client, line))
            return false;

        // Expected authentication command format: AUTH <username> <password>.
        std::istringstream input(line);
        std::string command;
        std::string password;
        input >> command >> username >> password;

        if (command != "AUTH" || !users_.authenticate(username, password)) {
            sendLine(client, "ERR Authentication failed");
            return false;
        }

        sendLine(client, "OK AUTH");
        std::cout << "[" << nowTime() << "] Client authenticated: " << username << "\n";
        return true;
    }

    void keepSubscriberOpen(SOCKET client)
    {
        std::string line;
        // Keep the subscription connection alive until the client disconnects
        // or sends QUIT, while publish() uses the same socket for notifications.
        while (recvLine(client, line)) {
            if (line == "QUIT")
                break;
        }
        broker_.remove(client);
        closesocket(client);
    }

    SOCKET listenSocket_ = INVALID_SOCKET;
    UserStore users_;
    ResourceRepository resource_;
    PubSubBroker broker_;
};

int main()
{
    WinsockSession winsock;
    if (!winsock.ok()) {
        std::cerr << "Failed to initialise Winsock.\n";
        return 1;
    }

    DistResServer server;
    if (!server.start()) {
        std::cerr << "Failed to start DistRes server on port " << DistResPort << ".\n";
        return 1;
    }

    server.run();
}

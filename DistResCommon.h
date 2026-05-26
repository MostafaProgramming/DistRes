#pragma once

#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <winsock2.h>
#include <ws2tcpip.h>

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <ctime>
#include <fstream>
#include <iostream>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

// Shared network endpoint used by the DistRes client and server.
// The current coursework demo runs locally, so 127.0.0.1 represents the
// server node on the same machine. The design still models client/server
// communication through TCP sockets rather than direct function calls.
constexpr int DistResPort = 54000;
constexpr const char* DistResHost = "127.0.0.1";

// Timestamp helper used in console output, logs, and demo evidence.
inline std::string nowTime()
{
    auto now = std::chrono::system_clock::now();
    std::time_t t = std::chrono::system_clock::to_time_t(now);
    std::tm local{};
    localtime_s(&local, &t);

    char buffer[16]{};
    std::strftime(buffer, sizeof(buffer), "%H:%M:%S", &local);
    return buffer;
}

inline std::string trimTrailingCarriageReturn(std::string value)
{
    // Windows telnet-style clients may send CRLF; DistRes normalises to LF.
    if (!value.empty() && value.back() == '\r')
        value.pop_back();
    return value;
}

inline bool sendLine(SOCKET socket, const std::string& line)
{
    // DistRes uses a simple newline-terminated text protocol over TCP.
    std::string payload = line + "\n";
    const char* data = payload.c_str();
    int remaining = static_cast<int>(payload.size());

    while (remaining > 0) {
        // send() may transmit only part of the payload, so keep sending until
        // the whole command or response has been written to the socket.
        int sent = send(socket, data, remaining, 0);
        if (sent == SOCKET_ERROR || sent == 0)
            return false;
        data += sent;
        remaining -= sent;
    }

    return true;
}

inline bool recvLine(SOCKET socket, std::string& line)
{
    line.clear();
    char ch = '\0';

    while (true) {
        // Read one byte at a time until the protocol newline is reached.
        int received = recv(socket, &ch, 1, 0);
        if (received == SOCKET_ERROR || received == 0)
            return false;
        if (ch == '\n') {
            line = trimTrailingCarriageReturn(line);
            return true;
        }
        line.push_back(ch);
    }
}

inline std::string sanitiseSingleLine(std::string text)
{
    // Protocol messages are line based, so embedded newlines are converted to
    // spaces before text is sent across the socket or appended to notifications.
    for (char& ch : text) {
        if (ch == '\r' || ch == '\n')
            ch = ' ';
    }
    return text;
}

inline std::string escapeProtocolText(const std::string& text)
{
    std::string escaped;
    for (char ch : text) {
        if (ch == '\\') {
            escaped += "\\\\";
        } else if (ch == '\n') {
            escaped += "\\n";
        } else if (ch == '\r') {
            escaped += "\\r";
        } else {
            escaped.push_back(ch);
        }
    }
    return escaped;
}

inline std::string unescapeProtocolText(const std::string& text)
{
    std::string unescaped;
    for (std::size_t i = 0; i < text.size(); ++i) {
        if (text[i] == '\\' && i + 1 < text.size()) {
            char next = text[++i];
            if (next == 'n') {
                unescaped.push_back('\n');
            } else if (next == 'r') {
                unescaped.push_back('\r');
            } else {
                unescaped.push_back(next);
            }
        } else {
            unescaped.push_back(text[i]);
        }
    }
    return unescaped;
}

class WinsockSession {
public:
    WinsockSession()
    {
        // Windows socket programming requires WSAStartup before socket calls.
        ok_ = WSAStartup(MAKEWORD(2, 2), &data_) == 0;
    }

    ~WinsockSession()
    {
        // RAII cleanup ensures Winsock is released when main() exits.
        if (ok_)
            WSACleanup();
    }

    bool ok() const
    {
        return ok_;
    }

private:
    WSADATA data_{};
    bool ok_ = false;
};

class WriterFairRWLock {
public:
    void acquireRead()
    {
        std::unique_lock<std::mutex> lock(mutex_);
        // New readers wait if a writer is active or already queued.
        cv_.wait(lock, [&] { return !writerActive_ && waitingWriters_ == 0; });
        ++activeReaders_;
    }

    void releaseRead()
    {
        std::lock_guard<std::mutex> lock(mutex_);
        --activeReaders_;
        // When the last reader leaves, a waiting writer can be released.
        if (activeReaders_ == 0)
            cv_.notify_all();
    }

    void acquireWrite()
    {
        std::unique_lock<std::mutex> lock(mutex_);
        ++waitingWriters_;
        // Writers require the resource to be completely idle.
        cv_.wait(lock, [&] { return !writerActive_ && activeReaders_ == 0; });
        --waitingWriters_;
        writerActive_ = true;
    }

    void releaseWrite()
    {
        std::lock_guard<std::mutex> lock(mutex_);
        writerActive_ = false;
        // Wake both readers and writers so the next valid operation can enter.
        cv_.notify_all();
    }

private:
    // These fields are the shared state protected by mutex_.
    std::mutex mutex_;
    std::condition_variable cv_;
    int activeReaders_ = 0;
    int waitingWriters_ = 0;
    bool writerActive_ = false;
};

class ReadGuard {
public:
    explicit ReadGuard(WriterFairRWLock& lock)
        : lock_(lock)
    {
        // Acquire read access when the guard is created.
        lock_.acquireRead();
    }

    ~ReadGuard()
    {
        // Automatically release read access even if the caller returns early.
        lock_.releaseRead();
    }

private:
    WriterFairRWLock& lock_;
};

class WriteGuard {
public:
    explicit WriteGuard(WriterFairRWLock& lock)
        : lock_(lock)
    {
        // Acquire exclusive write access when the guard is created.
        lock_.acquireWrite();
    }

    ~WriteGuard()
    {
        // Automatically release exclusive access when the update is complete.
        lock_.releaseWrite();
    }

private:
    WriterFairRWLock& lock_;
};

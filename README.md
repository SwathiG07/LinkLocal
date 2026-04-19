# LinkLocal – Offline Peer-to-Peer Chat System

## Overview

LinkLocal is a decentralized peer-to-peer chat application that enables users to communicate **completely offline** over a local network (WiFi or hotspot).

It does not rely on any central server or internet connection. All communication happens directly between devices on the same network.

---

## Key Features

* Fully **offline communication** (no internet required)
* Peer-to-peer architecture (no central server)
* Direct messaging and group chats
* File sharing (images, documents, etc.)
* Message features: reply, edit, delete, reactions
* Typing indicators and seen receipts
* Automatic peer discovery on LAN
* End-to-end encrypted messaging

---

## How It Works

* Users connect to the same WiFi or hotspot
* The application automatically discovers nearby peers
* Secure connections are established between devices
* Messages and files are exchanged directly

---

## Security

* Each peer generates a unique RSA key pair
* Messages are encrypted using Fernet (symmetric encryption)
* Encryption keys are securely exchanged using RSA
* Ensures private and secure communication

---

## Superuser Dashboard

Each peer includes a local dashboard that provides:

* Group and member details
* Online / offline status
* Peer IP tracking
* Administrative controls (e.g., removing users)

---

## How to Run

### No Setup Required

* Only the executable file is needed:

```plaintext
linklocal.exe
```

* No need to download or run the full project

### Steps

1. Share the `.exe` file
2. Connect all users to the same WiFi / hotspot
3. Run `linklocal.exe`
4. Start chatting instantly

---

## Important Notes

* Works only within a local network (LAN)

* Internet connection is not required

* All users must be on the same network

* Share the `.exe` using Google Drive or similar platforms

* Avoid WhatsApp (it may convert `.exe` into `.zip`)

---

## Summary

LinkLocal enables secure, real-time communication in offline environments, combining peer-to-peer networking with encryption and a user-friendly interface.

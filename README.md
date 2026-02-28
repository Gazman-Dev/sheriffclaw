# Project Status

Pre‑Alpha — **Do not install in production yet**

---

# Sheriff Claw 🤠

**The AI Firewall for Secure Autonomous Agents**

Sheriff Claw lets you use powerful AI agents **without giving them access to your secrets or your system**.

It is a **safe, controlled alternative to Open Claw**, built for people who want real AI power *without* losing control,
privacy, or security.

---

## 🔐 The Three Promises

Sheriff Claw is built around three non‑negotiable guarantees:

### 1️⃣ No Public Internet Exposure

Your system is **never exposed to the public internet**.

* No open ports
* No inbound access
* No random scanning or drive‑by attacks

If someone doesn’t already have access to your Telegram account or your device, **they cannot even see you exist**.

---

### 2️⃣ AI Never Sees Your Secrets

Your AI agent **can never read your passwords, API keys, or tokens**.

* No secrets in environment variables
* No plaintext config files
* No prompt injection attacks

Even if the AI is manipulated, jailbroken, or hallucinating — **it has nothing to steal**.

---

### 3️⃣ You Approve Every Capability

The AI **cannot run arbitrary commands**.

* It can only access services you explicitly approve
* It cannot execute random system actions
* It cannot “hallucinate” permissions

You are always in control. The AI works *for* you, not *instead of* you.

---

## 🧠 What Is Sheriff Claw?

Sheriff Claw is the **first true AI firewall**.

It sits between:

* Your **AI agent** (smart, powerful, untrusted)
* Your **system and secrets** (trusted, protected)

The AI never touches raw secrets or devices directly.
Everything goes through the Sheriff.

> Think of it like this:
>
> * The AI is the worker
> * The Sheriff is the security guard
> * You are the boss

---

## 🔒 How It Works (Non‑Technical Overview)

Sheriff Claw uses **two separate communication channels**:

### 🛡️ The Sheriff Channel (Secure Control)

* A private Telegram channel
* Talks only to **the Sheriff program running on your device**
* Handles passwords, approvals, and permissions

The Sheriff is **not an AI**.
It is a strict, deterministic security program.

---

### 🤖 The AI Channel (The Worker)

* A separate Telegram channel
* Where you talk to your AI agent
* Used for tasks like:

    * Research
    * Writing code
    * Automation
    * Planning

The AI **cannot access the Sheriff channel**.

---

## 🔑 Secure Workflow Example

**Goal:** Post a daily tweet about trending news.

1. You tell the AI:
   *"Check the news and post the top story every morning."*

2. The AI realizes it needs an **X (Twitter) token**.

3. The Sheriff messages you privately:
   *"The AI needs an X token. Please provide it."*

4. You enter the token **securely**.

5. The Sheriff encrypts and stores it.

6. The AI sends tweet text to the Sheriff.

7. The Sheriff signs and posts the tweet.

✅ **Result:**

* The tweet is posted
* The AI never saw the token
* Nothing sensitive was exposed

---

## 🛡️ Why This Is Actually Safe

* **No social engineering:** The Sheriff cannot be tricked — it is not an AI
* **No prompt injection:** The AI has zero access to secrets
* **No persistence risk:** Secrets disappear after reboot until you unlock

---

## 🧩 Technical Architecture (For Developers)

### 🐍 Python‑Only, Isolated Services

* Written entirely in Python
* Each component runs as an isolated service
* Clear boundaries between responsibilities

---

### 🧪 Debug & Test First Design

* Every service has a **debug implementation**
* Used for:

    * Unit tests
    * Integration tests
    * Deterministic simulations

Production code never mixes with test logic.

---

### 🔐 Secrets Database

* Encrypted SQLite database
* Stores:

    * Secrets
    * Configs
    * Permissions

**Critical security property:**

* The master password is **never stored**
* It exists **only in RAM**
* After reboot, the system is locked

Even with root access, an attacker gets nothing.

---

## 🔒 End‑to‑End Secret Entry (Telegram)

Sheriff Claw only communicates via:

* Telegram channels
* Local device communication

### Why Telegram?

Telegram supports **inline HTML apps**.
Sheriff Claw uses them for secure secret entry:

1. Sheriff sends an HTML password form
2. You enter a secret
3. JavaScript encrypts it using the agent’s public key
4. Encrypted data is sent back via Telegram

No third‑party services.
No plaintext transmission.
True end‑to‑end encryption.

---

## 🚀 Quick Install (macOS)

```bash
curl -fsSL https://raw.githubusercontent.com/Gazman-Dev/sheriffclaw/main/install.sh | bash
```

The installer:

* Downloads Sheriff Claw
* Guides initial setup
* Connects Telegram channels

---

## 🖥️ Terminal Channel

Start an interactive session:

```bash
sheriff-ctl chat
```

Routing rules:

* Messages starting with `/` → **Sheriff**
* Everything else → **AI agent**

Examples:

* `/status`
* `/ yes I agree`
* `what should I automate next?`

---

**Sheriff Claw gives you real AI power — on your terms.** 🤠

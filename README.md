# HermiesRAT

**A lightweight Remote Administration Tool written in Python.** *(Work in progress)*

HermiesRAT is a Python-based RAT built for authorized testing and pentesting

> **Status:** Active development. Public release targeted for **December** at the latest.

---

## Features

| Feature | Description | Status |
| --- | --- | --- |
| Screenshot | Capture the target's screen on demand | ✅ |
| Camera | Capture from the target's webcam | ✅ |
| Shell Access | Interactive remote shell | ✅ |
| File Browser | Browse, upload, and download files | ✅ |
| Quick Commands | One-click task shortcuts | ✅ |
| Payload Injection | Inject payloads through `powershell` (Windows) or `sh` / `bash` (Linux) | ✅ |
| Builder | Generate and configure payloads | ✅ |
| OS Detection | Automatic target OS fingerprinting | ✅ |
| Data Logs | Session and command history | ✅ |
| Custom Color Tabs | Per-tab theming for the operator UI | ✅ |
| Kiwi / Mimikatz | Credential extraction integration | ✅ |
| Settings Tab | Configurable operator preferences | ✅ |
| SQLite DB | Optional persistent storage backend | ✅ |
| HMAC via JSON | Saved HMAC keys stored as JSON | ✅ |
| Path Scanning | Fixed path-scanning logic | ✅ |
| Map | Network / host map view | 🚧 WIP |
| Mic Listener | Remote microphone capture | 🔜 Coming soon |

**Legend:** ✅ implemented · 🚧 in progress · 🔜 planned

---

## Modules

| Module | Purpose |
| --- | --- |
| **Recon** | Host, network, and system enumeration |
| **Privesc** | Privilege escalation checks and helpers |
| **Process** | Process listing and `taskkill` |
| **Registry** | Windows registry read/write |
| **Troll** | Harmless prank commands for demos |

---

> Requirements and first-run instructions will be finalized with the December release.

> Usage docs and the builder walkthrough are coming with the release.

---

## Disclaimer

> **FOR EDUCATIONAL AND AUTHORIZED TESTING USE ONLY.**
>
> HermiesRAT is intended for use on devices you own or have **explicit, documented
> permission** to test. Do not deploy it against systems you are not authorized to access.
>
> MarbleSec accepts no responsibility or liability for how this software is used or
> operated, and it is provided **without warranty of any kind**, express or implied.

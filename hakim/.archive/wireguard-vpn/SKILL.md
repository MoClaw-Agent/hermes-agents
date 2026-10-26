---
name: wireguard-vpn
description: Use when setting up or debugging WireGuard tunnels on Linux.
---

# WireGuard VPN setup and debugging

## Setup workflow
1. Check tools exist: `which wg wg-quick` (package `wireguard-tools`).
2. Config lives at `/etc/wireguard/<iface>.conf`, root-only. NEVER `cat` it in a way that echoes keys; use:
   `sudo -n wg-quick strip <iface> | grep -vi key` to see structure (AllowedIPs, Endpoint, MTU) without secrets.
3. Bring up: `sudo -n wg-quick up <iface>`; verify: `sudo -n wg show`.
4. Enable at boot: `sudo systemctl enable wg-quick@<iface>`.

## Sudo without password prompts
If sudo needs a password you cannot/should not type into chat, ask the user to run once:
```
echo '<user> ALL=(root) NOPASSWD: /usr/bin/wg-quick, /usr/bin/wg' | sudo tee /etc/sudoers.d/wireguard && sudo chmod 440 /etc/sudoers.d/wireguard
```
Scoped NOPASSWD for just wg/wg-quick is the safe ask — never request full passwordless sudo, and never accept passwords pasted into chat (refuse and suggest rotating).

## Handshake diagnostics (the key technique)
`wg show` transfer counters are the ground truth:
- **0 B received after sending keepalives = no completed handshake.** The tunnel passes nothing even though the interface is up and routes exist. Don't trust `ip link` or ping alone.
- Re-check counters after ~60s (keepalive interval) to see if anything changes.

## Pitfalls
- **UDP port probes lie**: `nc -zvu host port` reports "succeeded" for ANY udp endpoint because UDP is connectionless — nothing comes back on a closed/filtered port either. It proves nothing about reachability. ICMP ping may also be blocked. Only the handshake counter proves connectivity.
- **Routing overlap check first**: compare local subnet (`ip route`) vs AllowedIPs. If AllowedIPs includes the local LAN, traffic blackholes — but if they differ, a broken handshake is NOT caused by routing.
- Common causes of no-handshake: server offline/unreachable, client public key not registered as peer on server (regenerated keypair), NAT/firewall dropping UDP replies, wrong Endpoint port.
- Server-side check: run `wg show` on the peer to see if handshakes from the client's public key arrive.

## Reference
See `references/session-notes.md` for a worked debugging transcript pattern.

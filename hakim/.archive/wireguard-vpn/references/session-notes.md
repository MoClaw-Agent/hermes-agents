# Worked debugging pattern (2026-08 session)

Scenario: client on 192.168.0.108/24, tunnel config routes only 192.168.1.0/24 via peer endpoint 77.172.224.199:51820.

Sequence that worked:
1. `wg-quick up wg0` succeeded; interface created, address + route installed.
2. `wg show`: `transfer: 0 B received, N B sent` and growing sent bytes → keepalives going out, no handshake ever completed.
3. Ruled out routing overlap: local LAN (192.168.0.0/24) ≠ AllowedIPs subnet (192.168.1.0/24), so the failure was not a route conflict.
4. `ping` to endpoint failed AND `nc -zvu host 51820` reported "succeeded" — demonstrating why UDP probes are worthless for WireGuard reachability.
5. Conclusion: server-side problem (offline, key not registered as peer, or NAT/firewall dropping UDP). Next diagnostic step was checking `wg show` on the server for incoming handshake attempts from the client public key.

Session ended unresolved (user needed to check server side) — do not present any specific fix as validated until a handshake is actually observed.

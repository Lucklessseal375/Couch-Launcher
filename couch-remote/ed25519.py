"""Checks the update signatures dev/sign-release.ps1 makes (an OpenSSH "SSHSIG" with an Ed25519 key), in plain Python.
Windows' ssh-keygen can check them too, but not every PC has it (Windows Sandbox doesn't), so update.py uses this.

Ed25519 verification is RFC 8032's reference code (section 6). It isn't constant-time, which only matters for
signing with a secret key; checking a public signature has nothing to leak.
"""
import base64
import hashlib

p = 2**255 - 19
q = 2**252 + 27742317777372353535851937790883648493
d = -121665 * pow(121666, -1, p) % p
SQRT_M1 = pow(2, (p - 1) // 4, p)


def _add(P, Q):
    A, B = (P[1] - P[0]) * (Q[1] - Q[0]) % p, (P[1] + P[0]) * (Q[1] + Q[0]) % p
    C, D = 2 * P[3] * Q[3] * d % p, 2 * P[2] * Q[2] % p
    E, F, G, H = B - A, D - C, D + C, B + A
    return E * F, G * H, F * G, E * H


def _mul(s, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P, s = _add(P, P), s >> 1
    return Q


def _equal(P, Q):
    return (P[0] * Q[2] - Q[0] * P[2]) % p == 0 and (P[1] * Q[2] - Q[1] * P[2]) % p == 0


def _recover_x(y, sign):
    if y >= p:
        return None
    x2 = (y * y - 1) * pow(d * y * y + 1, -1, p)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (p + 3) // 8, p)
    if (x * x - x2) % p:
        x = x * SQRT_M1 % p
    if (x * x - x2) % p:
        return None
    return p - x if (x & 1) != sign else x


def _decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % p)


_GY = 4 * pow(5, -1, p) % p
_G = (_recover_x(_GY, 0), _GY, 1, _recover_x(_GY, 0) * _GY % p)


def verify(public, msg, sig):
    """RFC 8032 Ed25519: is sig (64 bytes) a signature of msg by public (32 bytes)?"""
    if len(public) != 32 or len(sig) != 64:
        return False
    A, R = _decompress(public), _decompress(sig[:32])
    s = int.from_bytes(sig[32:], "little")
    if A is None or R is None or s >= q:
        return False
    h = int.from_bytes(hashlib.sha512(sig[:32] + public + msg).digest(), "little") % q
    return _equal(_mul(s, _G), _add(R, _mul(h, A)))


def _strings(b):
    """SSH wire format: a run of uint32-length-prefixed strings."""
    out = []
    while b:
        n = int.from_bytes(b[:4], "big")
        if len(b) < 4 + n:
            raise ValueError("truncated")
        out.append(b[4:4 + n])
        b = b[4 + n:]
    return out


def ssh_ed25519_key(line):
    """The 32-byte key from an allowed-signers line ("<name> ssh-ed25519 <base64>"), or None."""
    parts = line.split()
    if len(parts) < 3 or parts[1] != "ssh-ed25519":
        return None
    kind, key = _strings(base64.b64decode(parts[2]))
    return key if kind == b"ssh-ed25519" else None


def verify_sshsig(armored, msg, namespace, keys):
    """An `ssh-keygen -Y sign` signature (armored text) of msg, in namespace, by one of keys (32-byte Ed25519 keys)."""
    try:
        text = armored.decode("ascii") if isinstance(armored, bytes) else armored
        body = "".join(l for l in text.splitlines() if l and not l.startswith("-----"))
        blob = base64.b64decode(body)
        if blob[:6] != b"SSHSIG" or int.from_bytes(blob[6:10], "big") != 1:
            return False
        pub, ns, reserved, hash_alg, sig = _strings(blob[10:])
        (kind, key), (sig_kind, raw) = _strings(pub), _strings(sig)
        if kind != b"ssh-ed25519" or sig_kind != b"ssh-ed25519" or key not in keys or ns != namespace.encode():
            return False
        digest = {b"sha512": hashlib.sha512, b"sha256": hashlib.sha256}[hash_alg](msg).digest()
        signed = b"SSHSIG" + b"".join(len(x).to_bytes(4, "big") + x for x in (ns, reserved, hash_alg, digest))
        return verify(key, signed, raw)
    except (ValueError, KeyError, UnicodeDecodeError, base64.binascii.Error):
        return False

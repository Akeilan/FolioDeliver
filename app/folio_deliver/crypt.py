"""Password protection as Office does it (File > Info > Protect Presentation > Encrypt with
Password): ECMA-376 Agile Encryption, AES-256 with SHA-512, in a compound file with the data
spaces Office expects ([MS-OFFCRYPTO] 2.3.4.10-2.3.4.15). A file protected here opens in
PowerPoint with the same password, and the other way round."""
import base64
import hashlib
import hmac
import os
import struct
from xml.dom import minidom

from . import cfb

BLK_VERIFIER_IN = bytes.fromhex("fea7d2763b4b9e79")
BLK_VERIFIER_HASH = bytes.fromhex("d7aa0f6d3061344e")
BLK_KEY = bytes.fromhex("146e0be7abacd0d6")
BLK_HMAC_KEY = bytes.fromhex("5fb2ad010cb9e1f6")
BLK_HMAC_VALUE = bytes.fromhex("a0677f02b22c8433")
SEGMENT = 4096


class WrongPassword(Exception):
    pass


def _aes(key, iv, data, decrypt=False):
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    c = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    op = c.decryptor() if decrypt else c.encryptor()
    return op.update(data) + op.finalize()


def _pad(data, n=16):
    r = len(data) % n
    return data + b"\0" * ((n - r) % n)


def _h(*parts, alg="sha512"):
    m = hashlib.new(alg)
    for p in parts:
        m.update(p)
    return m.digest()


def _fix(b, n, fill=b"\x36"):
    return b[:n] if len(b) >= n else b + fill * (n - len(b))


def _password_hash(password, salt, spin, alg="sha512"):
    h = _h(salt, password.encode("utf-16-le"), alg=alg)
    for k in range(spin):
        h = _h(struct.pack("<I", k), h, alg=alg)
    return h


def _key(h, block, bits, alg="sha512"):
    return _fix(_h(h, block, alg=alg), bits // 8)


def _lp(s):
    """UNICODE-LP-P4: a length in bytes, UTF-16LE, padded to 4 bytes."""
    b = s.encode("utf-16-le")
    return struct.pack("<I", len(b)) + b + b"\0" * ((4 - len(b) % 4) % 4)


def _dataspaces():
    ver = _lp("Microsoft.Container.DataSpaces") + struct.pack("<HHHHHH", 1, 0, 1, 0, 1, 0)
    entry = struct.pack("<I", 1) + struct.pack("<I", 0) + _lp("EncryptedPackage") + _lp("StrongEncryptionDataSpace")
    dsmap = struct.pack("<II", 8, 1) + struct.pack("<I", len(entry) + 4) + entry
    dsdef = struct.pack("<II", 8, 1) + _lp("StrongEncryptionTransform")
    tid = _lp("{FF9A3F03-56EF-4613-BDD5-5A41C1D07246}")
    head = struct.pack("<I", 1) + tid
    primary = struct.pack("<I", len(head) + 4) + head + _lp("Microsoft.Container.EncryptionTransform") + \
        struct.pack("<HHHHHH", 1, 0, 1, 0, 1, 0) + struct.pack("<IIII", 0, 0, 0, 4)
    return {
        "\x06DataSpaces/Version": ver,
        "\x06DataSpaces/DataSpaceMap": dsmap,
        "\x06DataSpaces/DataSpaceInfo/StrongEncryptionDataSpace": dsdef,
        "\x06DataSpaces/TransformInfo/StrongEncryptionTransform/\x06Primary": primary,
    }


def encrypt(package, password, spin=100000):
    """An Office package (.pptx bytes) encrypted with `password`: compound-file bytes."""
    key_salt = os.urandom(16)
    pw_salt = os.urandom(16)
    secret = os.urandom(32)
    # the package, in 4096-byte segments
    out = bytearray(struct.pack("<Q", len(package)))
    for k in range(0, max(1, (len(package) + SEGMENT - 1) // SEGMENT)):
        seg = package[k * SEGMENT:(k + 1) * SEGMENT]
        iv = _h(key_salt, struct.pack("<I", k))[:16]
        out += _aes(secret, iv, _pad(seg))
    enc_pkg = bytes(out)
    # integrity
    hmac_key = os.urandom(64)
    iv1 = _h(key_salt, BLK_HMAC_KEY)[:16]
    iv2 = _h(key_salt, BLK_HMAC_VALUE)[:16]
    hmac_value = hmac.new(hmac_key, enc_pkg, hashlib.sha512).digest()
    enc_hmac_key = _aes(secret, iv1, hmac_key)
    enc_hmac_value = _aes(secret, iv2, hmac_value)
    # the password's keys
    ph = _password_hash(password, pw_salt, spin)
    verifier = os.urandom(16)
    enc_vin = _aes(_key(ph, BLK_VERIFIER_IN, 256), pw_salt, verifier)
    enc_vhash = _aes(_key(ph, BLK_VERIFIER_HASH, 256), pw_salt, _h(verifier))
    enc_key = _aes(_key(ph, BLK_KEY, 256), pw_salt, secret)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
           '<encryption xmlns="http://schemas.microsoft.com/office/2006/encryption" '
           'xmlns:p="http://schemas.microsoft.com/office/2006/keyEncryptor/password" '
           'xmlns:c="http://schemas.microsoft.com/office/2006/keyEncryptor/certificate">'
           '<keyData saltSize="16" blockSize="16" keyBits="256" hashSize="64" cipherAlgorithm="AES" '
           'cipherChaining="ChainingModeCBC" hashAlgorithm="SHA512" saltValue="%s"/>'
           '<dataIntegrity encryptedHmacKey="%s" encryptedHmacValue="%s"/>'
           '<keyEncryptors><keyEncryptor uri="http://schemas.microsoft.com/office/2006/keyEncryptor/password">'
           '<p:encryptedKey spinCount="%d" saltSize="16" blockSize="16" keyBits="256" hashSize="64" cipherAlgorithm="AES" '
           'cipherChaining="ChainingModeCBC" hashAlgorithm="SHA512" saltValue="%s" encryptedVerifierHashInput="%s" '
           'encryptedVerifierHashValue="%s" encryptedKeyValue="%s"/></keyEncryptor></keyEncryptors></encryption>'
           % (b64(key_salt), b64(enc_hmac_key), b64(enc_hmac_value), spin, b64(pw_salt), b64(enc_vin), b64(enc_vhash),
              b64(enc_key)))
    info = struct.pack("<HHI", 4, 4, 0x40) + xml.encode("utf-8")
    streams = {"EncryptionInfo": info, "EncryptedPackage": enc_pkg}
    streams.update(_dataspaces())
    return cfb.write(streams)


def is_encrypted(data):
    if not cfb.is_cfb(data):
        return False
    try:
        st = cfb.read(data)
    except Exception:
        return False
    return "EncryptionInfo" in st and "EncryptedPackage" in st


def decrypt(data, password):
    """The package inside an encrypted Office file; WrongPassword when it doesn't open it."""
    st = cfb.read(data)
    info, enc = st["EncryptionInfo"], st["EncryptedPackage"]
    vmaj, vmin, _flags = struct.unpack_from("<HHI", info, 0)
    if (vmaj, vmin) != (4, 4):
        return _decrypt_standard(info, enc, password)
    doc = minidom.parseString(info[8:].decode("utf-8", "replace").lstrip("﻿"))
    kd = doc.getElementsByTagName("keyData")[0]
    ek = [e for e in doc.getElementsByTagName("*") if e.localName == "encryptedKey"][0]
    alg = ek.getAttribute("hashAlgorithm").lower().replace("-", "")
    alg = {"sha1": "sha1", "sha256": "sha256", "sha384": "sha384", "sha512": "sha512"}.get(alg, "sha512")
    bits = int(ek.getAttribute("keyBits") or 256)
    salt = base64.b64decode(ek.getAttribute("saltValue"))
    spin = int(ek.getAttribute("spinCount") or 100000)
    ph = _password_hash(password, salt, spin, alg)
    blk = int(ek.getAttribute("blockSize") or 16)
    vin = _aes(_key(ph, BLK_VERIFIER_IN, bits, alg), salt[:blk], base64.b64decode(ek.getAttribute("encryptedVerifierHashInput")), True)
    vh = _aes(_key(ph, BLK_VERIFIER_HASH, bits, alg), salt[:blk], base64.b64decode(ek.getAttribute("encryptedVerifierHashValue")), True)
    hs = int(ek.getAttribute("hashSize") or 64)
    if _h(vin[:int(ek.getAttribute("saltSize") or 16)], alg=alg)[:hs] != vh[:hs]:
        raise WrongPassword()
    secret = _aes(_key(ph, BLK_KEY, bits, alg), salt[:blk], base64.b64decode(ek.getAttribute("encryptedKeyValue")), True)
    secret = secret[:int(kd.getAttribute("keyBits") or 256) // 8]
    ksalt = base64.b64decode(kd.getAttribute("saltValue"))
    kalg = kd.getAttribute("hashAlgorithm").lower().replace("-", "") or "sha512"
    size = struct.unpack_from("<Q", enc, 0)[0]
    out = bytearray()
    body = enc[8:]
    for k in range(0, (len(body) + SEGMENT - 1) // SEGMENT):
        seg = body[k * SEGMENT:(k + 1) * SEGMENT]
        iv = _h(ksalt, struct.pack("<I", k), alg=kalg)[:16]
        out += _aes(secret, iv, _pad(seg), True)
    return bytes(out[:size])


def _decrypt_standard(info, enc, password):
    """Office 2007's Standard Encryption (AES-128, SHA-1), for older protected files."""
    import io
    r = io.BytesIO(info[8:])
    hsize = struct.unpack("<I", r.read(4))[0]
    hdr = r.read(hsize)
    keybits = struct.unpack_from("<I", hdr, 16)[0] or 128
    ver = r.read()
    salt_size = struct.unpack_from("<I", ver, 0)[0]
    salt = ver[4:4 + salt_size]
    enc_verifier = ver[4 + salt_size:20 + salt_size]
    enc_vhash = ver[24 + salt_size:56 + salt_size]
    h = _h(salt, password.encode("utf-16-le"), alg="sha1")
    for k in range(50000):
        h = _h(struct.pack("<I", k), h, alg="sha1")
    h = _h(h, struct.pack("<I", 0), alg="sha1")
    b1 = bytearray(b"\x36" * 64)
    b2 = bytearray(b"\x5c" * 64)
    for k, c in enumerate(h):
        b1[k] ^= c
        b2[k] ^= c
    x1 = _h(bytes(b1), alg="sha1")
    x2 = _h(bytes(b2), alg="sha1")
    key = (x1 + x2)[:keybits // 8]
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    dec = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend()).decryptor()
    v = dec.update(enc_verifier)
    vh = dec.update(enc_vhash)
    if _h(v, alg="sha1") != vh[:20]:
        raise WrongPassword()
    size = struct.unpack_from("<Q", enc, 0)[0]
    d2 = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend()).decryptor()
    return (d2.update(_pad(enc[8:])) + d2.finalize())[:size]

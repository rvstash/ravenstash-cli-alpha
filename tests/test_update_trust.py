from __future__ import annotations

import base64
import hashlib
import textwrap
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from rvs import update_trust
from rvs.update_trust import VerificationError, verify_detached


if TYPE_CHECKING:
    from collections.abc import Callable


FIXTURES = Path(__file__).parent / "fixtures"
INVENTORY = (FIXTURES / "rvs-v0.14.3-checksums.txt").read_bytes()
INVENTORY_SIGNATURE = (FIXTURES / "rvs-v0.14.3-checksums.txt.asc").read_bytes()

SIGNATURE_TAG = 2
PUBLIC_KEY_TAG = 6
USER_ID_TAG = 13
RSA = 1
RSA_SIGN_ONLY = 3
SHA256 = 8
SHA384 = 9
SHA512 = 10
_DIGESTS = {SHA256: hashlib.sha256, SHA384: hashlib.sha384, SHA512: hashlib.sha512}

# An insecure but reproducible RSA key built from the Mersenne primes M607 and M521.
# It lets tests sign fresh documents without committing private key material.
_TOY_P = 2**607 - 1
_TOY_Q = 2**521 - 1
_TOY_EXPONENT = 65537
TOY_PUBLIC_KEY = update_trust._RSAKey(_TOY_EXPONENT, _TOY_P * _TOY_Q)


def _unarmor(armored: bytes) -> bytes:
    """Decode a well-formed armor block independently of the code under test."""
    lines = armored.decode("ascii").splitlines()
    payload = lines[lines.index("") + 1 : -1]
    return base64.b64decode("".join(line for line in payload if not line.startswith("=")))


def _old_format_packet_body(packet: bytes, tag: int) -> bytes:
    """Return the body of one old-format packet framed with a two-octet length."""
    assert packet[0] == 0x80 | tag << 2 | 0x01
    length = int.from_bytes(packet[1:3])
    assert len(packet) == 3 + length
    return packet[3:]


FIXTURE_SIGNATURE = _unarmor(INVENTORY_SIGNATURE)
FIXTURE_BODY = _old_format_packet_body(FIXTURE_SIGNATURE, SIGNATURE_TAG)
FIXTURE_HASHED_END = 6 + int.from_bytes(FIXTURE_BODY[4:6])
FIXTURE_HEADER = FIXTURE_BODY[:FIXTURE_HASHED_END]
FIXTURE_UNHASHED_LENGTH = int.from_bytes(FIXTURE_BODY[FIXTURE_HASHED_END : FIXTURE_HASHED_END + 2])
FIXTURE_UNHASHED_END = FIXTURE_HASHED_END + 2 + FIXTURE_UNHASHED_LENGTH
FIXTURE_SIGNATURE_MPI = FIXTURE_BODY[FIXTURE_UNHASHED_END + 2 :]

RELEASE_KEY_ARMOR = files("rvs.resources").joinpath("ravenstash-rvs.asc").read_bytes()
RELEASE_KEY = _unarmor(RELEASE_KEY_ARMOR)
RELEASE_KEY_BODY = _old_format_packet_body(
    RELEASE_KEY[: 3 + int.from_bytes(RELEASE_KEY[1:3])], PUBLIC_KEY_TAG
)


def _packet(tag: int, body: bytes) -> bytes:
    """Frame a packet with an old-format four-octet length."""
    return bytes([0x80 | tag << 2 | 0x02]) + len(body).to_bytes(4, "big") + body


def _new_format_packet(tag: int, body: bytes) -> bytes:
    """Frame a packet with the shortest new-format length (one or two octets)."""
    if len(body) < 192:
        return bytes([0xC0 | tag, len(body)]) + body
    encoded = len(body) - 192
    return bytes([0xC0 | tag, (encoded >> 8) + 192, encoded & 0xFF]) + body


def _new_format_five_octet_packet(tag: int, body: bytes) -> bytes:
    return bytes([0xC0 | tag, 0xFF]) + len(body).to_bytes(4, "big") + body


def _armor(binary: bytes, *, headers: tuple[str, ...] = (), newline: str = "\n") -> bytes:
    lines = [
        "-----BEGIN PGP SIGNATURE-----",
        *headers,
        "",
        *textwrap.wrap(base64.b64encode(binary).decode("ascii"), 64),
        "-----END PGP SIGNATURE-----",
        "",
    ]
    return newline.join(lines).encode("ascii")


def _mpi(value: int) -> bytes:
    bits = value.bit_length()
    return bits.to_bytes(2, "big") + value.to_bytes((bits + 7) // 8, "big")


def _v4_header(*, hash_algorithm: int = SHA256, public_key_algorithm: int = RSA) -> bytes:
    """A v4 binary-document signature header with an empty hashed subpacket area."""
    return bytes([4, 0x00, public_key_algorithm, hash_algorithm]) + (0).to_bytes(2, "big")


def _signed_message(subject: bytes, header: bytes) -> bytes:
    """The exact byte stream an OpenPGP v4 signature hashes (RFC 4880, section 5.2.4)."""
    return subject + header + b"\x04\xff" + len(header).to_bytes(4, "big")


def _signature_body(subject: bytes, header: bytes, signature_mpi: bytes) -> bytes:
    """Assemble a signature body whose two-octet digest prefix matches ``subject``."""
    digest = _DIGESTS[header[3]](_signed_message(subject, header)).digest()
    return header + (0).to_bytes(2, "big") + digest[:2] + signature_mpi


def _verification_error(subject: bytes, signature: bytes) -> str:
    with pytest.raises(VerificationError) as raised:
        verify_detached(subject, signature)
    return str(raised.value)


@pytest.fixture
def toy_signer() -> Callable[[bytes, int], int]:
    """Sign with the toy key through an independent PKCS #1 v1.5 implementation."""
    rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    phi = (_TOY_P - 1) * (_TOY_Q - 1)
    private_exponent = pow(_TOY_EXPONENT, -1, phi)
    private_key = rsa.RSAPrivateNumbers(
        p=_TOY_P,
        q=_TOY_Q,
        d=private_exponent,
        dmp1=rsa.rsa_crt_dmp1(private_exponent, _TOY_P),
        dmq1=rsa.rsa_crt_dmq1(private_exponent, _TOY_Q),
        iqmp=rsa.rsa_crt_iqmp(_TOY_P, _TOY_Q),
        public_numbers=rsa.RSAPublicNumbers(_TOY_EXPONENT, _TOY_P * _TOY_Q),
    ).private_key(unsafe_skip_rsa_key_validation=True)
    algorithms = {SHA256: hashes.SHA256(), SHA384: hashes.SHA384(), SHA512: hashes.SHA512()}

    def sign(message: bytes, hash_algorithm: int) -> int:
        signature = private_key.sign(message, padding.PKCS1v15(), algorithms[hash_algorithm])
        return int.from_bytes(signature)

    return sign


@pytest.fixture
def trust_toy_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_trust, "_release_key", lambda: TOY_PUBLIC_KEY)


def _toy_signature(
    sign: Callable[[bytes, int], int],
    subject: bytes,
    *,
    hash_algorithm: int = SHA256,
    public_key_algorithm: int = RSA,
) -> bytes:
    header = _v4_header(hash_algorithm=hash_algorithm, public_key_algorithm=public_key_algorithm)
    signature = sign(_signed_message(subject, header), hash_algorithm)
    return _packet(SIGNATURE_TAG, _signature_body(subject, header, _mpi(signature)))


# ── Armor ─────────────────────────────────────────────────────────────────────


def test_published_signature_verifies_from_binary_and_reframed_armor() -> None:
    verify_detached(INVENTORY, FIXTURE_SIGNATURE)
    verify_detached(INVENTORY, _armor(FIXTURE_SIGNATURE))


def test_armor_headers_and_crlf_line_endings_are_accepted() -> None:
    armored = _armor(
        FIXTURE_SIGNATURE,
        headers=("Version: GnuPG v2", "Comment: release inventory"),
        newline="\r\n",
    )

    verify_detached(INVENTORY, armored)


@pytest.mark.parametrize(
    "armored",
    [
        pytest.param(b"-----BEGIN PGP SIGNATURE-----\n", id="no-blank-separator"),
        pytest.param(
            b"-----BEGIN PGP SIGNATURE-----\n\n=boTv\n-----END PGP SIGNATURE-----\n",
            id="checksum-only",
        ),
    ],
)
def test_armor_without_payload_is_rejected(armored: bytes) -> None:
    assert _verification_error(INVENTORY, armored) == "OpenPGP armor contains no payload"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"iQIz!!!!", id="invalid-base64"),
        pytest.param("iQé".encode(), id="non-ascii"),
    ],
)
def test_malformed_armor_payload_is_rejected(payload: bytes) -> None:
    armored = b"-----BEGIN PGP SIGNATURE-----\n\n" + payload + b"\n-----END PGP SIGNATURE-----\n"

    assert _verification_error(INVENTORY, armored) == "OpenPGP armor is invalid"


# ── Packet framing ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "frame",
    [
        pytest.param(_packet, id="old-format-four-octet"),
        pytest.param(_new_format_packet, id="new-format-two-octet"),
        pytest.param(_new_format_five_octet_packet, id="new-format-five-octet"),
    ],
)
def test_every_definite_length_encoding_frames_the_same_signature(
    frame: Callable[[int, bytes], bytes],
) -> None:
    verify_detached(INVENTORY, frame(SIGNATURE_TAG, FIXTURE_BODY))


@pytest.mark.parametrize(
    ("data", "message"),
    [
        pytest.param(b"\x08\x00", "invalid OpenPGP packet header", id="high-bit-clear"),
        pytest.param(
            FIXTURE_SIGNATURE + b"\x00",
            "invalid OpenPGP packet header",
            id="garbage-after-valid-packet",
        ),
        pytest.param(b"\xc2", "truncated OpenPGP packet", id="new-format-without-length"),
        pytest.param(
            b"\xc2\xc0", "truncated OpenPGP packet length", id="new-format-two-octet-length"
        ),
        pytest.param(
            b"\xc2\xff\x00\x00\x02",
            "truncated OpenPGP packet length",
            id="new-format-five-octet-length",
        ),
        pytest.param(
            b"\xc2\xe0\x00",
            "partial OpenPGP packet lengths are unsupported",
            id="new-format-smallest-partial-length",
        ),
        pytest.param(
            b"\xc2\xfe\x00",
            "partial OpenPGP packet lengths are unsupported",
            id="new-format-largest-partial-length",
        ),
        pytest.param(
            b"\x8b\x00",
            "indeterminate or truncated OpenPGP packet",
            id="old-format-indeterminate-length",
        ),
        pytest.param(
            b"\x88",
            "indeterminate or truncated OpenPGP packet",
            id="old-format-one-octet-length",
        ),
        pytest.param(
            b"\x89\x02",
            "indeterminate or truncated OpenPGP packet",
            id="old-format-two-octet-length",
        ),
        pytest.param(
            b"\x8a\x00\x00\x02",
            "indeterminate or truncated OpenPGP packet",
            id="old-format-four-octet-length",
        ),
        pytest.param(b"\x88\x04abc", "truncated OpenPGP packet body", id="old-format-body"),
        pytest.param(b"\xc2\x04abc", "truncated OpenPGP packet body", id="new-format-body"),
        pytest.param(
            b"\xc2\xbf" + bytes(190),
            "truncated OpenPGP packet body",
            id="new-format-largest-one-octet-body",
        ),
        pytest.param(
            b"\xc2\xc0\x00" + bytes(191),
            "truncated OpenPGP packet body",
            id="new-format-smallest-two-octet-body",
        ),
        pytest.param(
            b"\xc2\xdf\xff" + bytes(8382),
            "truncated OpenPGP packet body",
            id="new-format-largest-two-octet-body",
        ),
        pytest.param(
            b"\xc2\xff\xff\xff\xff\xff",
            "truncated OpenPGP packet body",
            id="new-format-five-octet-body",
        ),
    ],
)
def test_malformed_packet_framing_is_rejected(data: bytes, message: str) -> None:
    assert _verification_error(INVENTORY, data) == message


@pytest.mark.parametrize(
    "signature",
    [
        pytest.param(b"", id="empty"),
        pytest.param(FIXTURE_SIGNATURE + FIXTURE_SIGNATURE, id="two-signatures"),
        pytest.param(RELEASE_KEY_ARMOR, id="public-key-block"),
        pytest.param(_new_format_packet(USER_ID_TAG, b"rvs"), id="user-id"),
    ],
)
def test_detached_signature_must_be_exactly_one_signature_packet(signature: bytes) -> None:
    assert _verification_error(INVENTORY, signature) == "expected one OpenPGP signature packet"


# ── Signature metadata ────────────────────────────────────────────────────────


def _replace_byte(body: bytes, offset: int, value: int) -> bytes:
    return body[:offset] + bytes([value]) + body[offset + 1 :]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(FIXTURE_BODY[:11], id="shorter-than-fixed-fields"),
        pytest.param(_replace_byte(FIXTURE_BODY, 0, 3), id="version-3"),
        pytest.param(_replace_byte(FIXTURE_BODY, 1, 0x01), id="canonical-text-document"),
        pytest.param(_replace_byte(FIXTURE_BODY, 1, 0x13), id="key-certification"),
        pytest.param(_replace_byte(FIXTURE_BODY, 2, 17), id="dsa"),
        pytest.param(_replace_byte(FIXTURE_BODY, 2, 22), id="eddsa"),
    ],
)
def test_only_v4_rsa_binary_document_signatures_are_accepted(body: bytes) -> None:
    signature = _packet(SIGNATURE_TAG, body)

    assert _verification_error(INVENTORY, signature) == "unsupported OpenPGP release signature"


@pytest.mark.parametrize(
    "hash_algorithm",
    [pytest.param(1, id="md5"), pytest.param(2, id="sha1"), pytest.param(11, id="sha224")],
)
def test_weak_or_unknown_signature_hashes_are_rejected(hash_algorithm: int) -> None:
    signature = _packet(SIGNATURE_TAG, _replace_byte(FIXTURE_BODY, 3, hash_algorithm))

    assert _verification_error(INVENTORY, signature) == "unsupported OpenPGP signature hash"


def test_hashed_area_longer_than_the_signature_is_rejected() -> None:
    body = FIXTURE_BODY[:4] + b"\xff\xff" + FIXTURE_BODY[6:]

    message = _verification_error(INVENTORY, _packet(SIGNATURE_TAG, body))

    assert message == "truncated OpenPGP signature metadata"


def test_unhashed_area_longer_than_the_signature_is_rejected() -> None:
    body = FIXTURE_HEADER + b"\xff\xff" + FIXTURE_BODY[FIXTURE_HASHED_END + 2 :]

    message = _verification_error(INVENTORY, _packet(SIGNATURE_TAG, body))

    assert message == "truncated OpenPGP signature"


@pytest.mark.parametrize(
    ("signature_mpi", "message"),
    [
        pytest.param(b"", "truncated OpenPGP MPI", id="missing-bit-count"),
        pytest.param(b"\x10", "truncated OpenPGP MPI", id="partial-bit-count"),
        pytest.param(FIXTURE_SIGNATURE_MPI[:-1], "truncated OpenPGP MPI", id="missing-final-octet"),
        pytest.param(b"\x00\x10\x00\x01", "non-canonical OpenPGP MPI", id="leading-zero-octet"),
        pytest.param(
            FIXTURE_SIGNATURE_MPI + b"\x00",
            "unexpected data after OpenPGP signature",
            id="trailing-data",
        ),
    ],
)
def test_malformed_signature_value_is_rejected(signature_mpi: bytes, message: str) -> None:
    body = _signature_body(INVENTORY, FIXTURE_HEADER, signature_mpi)

    assert _verification_error(INVENTORY, _packet(SIGNATURE_TAG, body)) == message


# ── Authentication ────────────────────────────────────────────────────────────


def test_modified_document_fails_the_digest_prefix_check() -> None:
    message = _verification_error(INVENTORY + b"changed\n", INVENTORY_SIGNATURE)

    assert message == "OpenPGP signature digest prefix does not match"


def test_modified_hashed_subpacket_fails_the_digest_prefix_check() -> None:
    # The last hashed octet belongs to the signature creation-time subpacket.
    body = _replace_byte(
        FIXTURE_BODY, FIXTURE_HASHED_END - 1, FIXTURE_BODY[FIXTURE_HASHED_END - 1] ^ 1
    )

    message = _verification_error(INVENTORY, _packet(SIGNATURE_TAG, body))

    assert message == "OpenPGP signature digest prefix does not match"


def test_genuine_signature_value_cannot_be_replayed_onto_another_document() -> None:
    forged = _signature_body(b"another inventory\n", FIXTURE_HEADER, FIXTURE_SIGNATURE_MPI)

    message = _verification_error(b"another inventory\n", _packet(SIGNATURE_TAG, forged))

    assert message == "OpenPGP release signature is invalid"


@pytest.mark.parametrize(
    "signature_value",
    [
        pytest.param(update_trust._release_key().modulus, id="equal-to-modulus"),
        pytest.param(1 << 4096, id="wider-than-modulus"),
    ],
)
def test_signature_value_outside_the_key_modulus_is_rejected(signature_value: int) -> None:
    body = _signature_body(INVENTORY, FIXTURE_HEADER, _mpi(signature_value))

    message = _verification_error(INVENTORY, _packet(SIGNATURE_TAG, body))

    assert message == "OpenPGP release signature is invalid"


def test_signature_from_another_rsa_key_is_rejected(
    toy_signer: Callable[[bytes, int], int],
) -> None:
    signature = _toy_signature(toy_signer, INVENTORY)

    assert _verification_error(INVENTORY, signature) == "OpenPGP release signature is invalid"


@pytest.mark.parametrize(
    ("hash_algorithm", "public_key_algorithm"),
    [
        pytest.param(SHA256, RSA, id="sha256"),
        pytest.param(SHA384, RSA, id="sha384"),
        pytest.param(SHA512, RSA, id="sha512"),
        pytest.param(SHA256, RSA_SIGN_ONLY, id="rsa-sign-only"),
    ],
)
@pytest.mark.usefixtures("trust_toy_key")
def test_supported_hashes_match_an_independent_pkcs1_signer(
    toy_signer: Callable[[bytes, int], int], hash_algorithm: int, public_key_algorithm: int
) -> None:
    signature = _toy_signature(
        toy_signer,
        b"inventory\n",
        hash_algorithm=hash_algorithm,
        public_key_algorithm=public_key_algorithm,
    )

    verify_detached(b"inventory\n", signature)
    verify_detached(b"inventory\n", _armor(signature))


@pytest.mark.parametrize(
    ("modulus_bits", "message"),
    [
        # A SHA-256 DigestInfo is 51 octets; PKCS #1 v1.5 needs 11 more, 8 of them padding.
        pytest.param(496, "OpenPGP release signature is invalid", id="minimum-size"),
        pytest.param(
            488,
            "OpenPGP release key is too small for its signature hash",
            id="one-octet-too-small",
        ),
    ],
)
def test_key_must_leave_room_for_eight_padding_octets(
    monkeypatch: pytest.MonkeyPatch, modulus_bits: int, message: str
) -> None:
    small_key = update_trust._RSAKey(_TOY_EXPONENT, (1 << modulus_bits - 1) | 1)
    monkeypatch.setattr(update_trust, "_release_key", lambda: small_key)
    header = _v4_header(hash_algorithm=SHA256)
    body = _signature_body(INVENTORY, header, _mpi(2))

    assert _verification_error(INVENTORY, _packet(SIGNATURE_TAG, body)) == message


# ── Pinned release key ────────────────────────────────────────────────────────


def _install_release_key(monkeypatch: pytest.MonkeyPatch, directory: Path, key: bytes) -> None:
    (directory / "ravenstash-rvs.asc").write_bytes(key)
    monkeypatch.setattr(update_trust, "files", lambda _package: directory)


def test_release_key_without_a_public_key_packet_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_release_key(monkeypatch, tmp_path, _packet(USER_ID_TAG, b"Ravenstash"))

    with pytest.raises(VerificationError, match=r"^release key has no public-key packet$"):
        update_trust._release_key()


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(RELEASE_KEY_BODY[:5], id="shorter-than-fixed-fields"),
        pytest.param(_replace_byte(RELEASE_KEY_BODY, 0, 3), id="version-3"),
        pytest.param(_replace_byte(RELEASE_KEY_BODY, 5, 17), id="dsa"),
        pytest.param(_replace_byte(RELEASE_KEY_BODY, 5, 22), id="eddsa"),
    ],
)
def test_release_key_must_be_an_rsa_v4_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: bytes
) -> None:
    _install_release_key(monkeypatch, tmp_path, _packet(PUBLIC_KEY_TAG, body))

    with pytest.raises(VerificationError, match=r"^release key is not a supported RSA v4 key$"):
        update_trust._release_key()


def test_substituted_release_key_does_not_match_the_pinned_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    substituted = _replace_byte(RELEASE_KEY_BODY, len(RELEASE_KEY_BODY) - 1, 0x03)
    _install_release_key(monkeypatch, tmp_path, _packet(PUBLIC_KEY_TAG, substituted))

    with pytest.raises(
        VerificationError, match=r"^release key fingerprint does not match the pinned identity$"
    ):
        update_trust._release_key()

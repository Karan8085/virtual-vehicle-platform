"""
OTA Package & Manifest Structure (Section 4.1).

What this file does:
Defines the structure of a secure Over-The-Air software update package:
- Target ECU identity & Hardware compatibility ID
- Target software version & monotonic security version counter (for anti-downgrade)
- Dependencies (e.g. requires Gateway v1.0.0+)
- Binary payload split into verifiable chunks with individual SHA-256 hashes
- Full image SHA-256 hash
- Cryptographic digital signature signed by OEM private key
"""

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


@dataclass
class OTAPackageManifest:
    """Manifest describing update package metadata and integrity proofs."""
    package_id: str
    target_ecu: str                      # E.g. "Powertrain_ECU"
    target_hw_id: str                    # E.g. "HW_PT_V1"
    target_version: str                  # E.g. "v1.1.0"
    version_counter: int                 # Monotonic counter: must be >= current counter to prevent downgrade
    dependencies: Dict[str, str] = field(default_factory=dict) # E.g. {"Gateway_ECU": "v1.0.0"}
    total_size_bytes: int = 0
    chunk_size_bytes: int = 256
    chunk_hashes: List[str] = field(default_factory=list)
    full_image_hash: str = ""
    digital_signature: str = ""
    signer_cn: str = "Automotive_OEM_Firmware_Signer_CA"
    signer_revoked: bool = False
    signer_expired: bool = False


class OTAPackageBuilder:
    """Helper to create and sign test update packages."""

    # Pre-shared signing key for simulated asymmetric ECDSA/HMAC signature
    OEM_SIGNING_KEY = b"AUTOMOTIVE_OEM_TRUSTED_ROOT_KEY_2026"

    @classmethod
    def create_package(cls, package_id: str, target_ecu: str, target_hw: str,
                       version: str, version_counter: int, payload: bytes,
                       chunk_size: int = 256,
                       dependencies: Optional[Dict[str, str]] = None) -> Tuple[OTAPackageManifest, List[bytes]]:
        """Splits payload into chunks, calculates SHA-256 hashes, and signs the manifest."""
        chunks: List[bytes] = []
        chunk_hashes: List[str] = []

        for i in range(0, len(payload), chunk_size):
            chunk = payload[i:i + chunk_size]
            chunks.append(chunk)
            chunk_hashes.append(hashlib.sha256(chunk).hexdigest())

        full_hash = hashlib.sha256(payload).hexdigest()

        # Generate digital signature over manifest critical metadata + full hash
        sign_data = f"{package_id}:{target_ecu}:{target_hw}:{version}:{version_counter}:{full_hash}".encode("utf-8")
        signature = hmac.new(cls.OEM_SIGNING_KEY, sign_data, hashlib.sha256).hexdigest()

        manifest = OTAPackageManifest(
            package_id=package_id,
            target_ecu=target_ecu,
            target_hw_id=target_hw,
            target_version=version,
            version_counter=version_counter,
            dependencies=dependencies or {},
            total_size_bytes=len(payload),
            chunk_size_bytes=chunk_size,
            chunk_hashes=chunk_hashes,
            full_image_hash=full_hash,
            digital_signature=signature
        )

        return manifest, chunks

    @classmethod
    def verify_signature(cls, manifest: OTAPackageManifest) -> Tuple[bool, str]:
        """Verifies digital signature against OEM root key."""
        if manifest.signer_revoked:
            return False, "SIGNER_REVOKED: The signing certificate has been revoked!"
        if manifest.signer_expired:
            return False, "SIGNER_EXPIRED: The signing certificate has expired!"

        sign_data = (f"{manifest.package_id}:{manifest.target_ecu}:{manifest.target_hw_id}:"
                     f"{manifest.target_version}:{manifest.version_counter}:{manifest.full_image_hash}").encode("utf-8")
        expected_sig = hmac.new(cls.OEM_SIGNING_KEY, sign_data, hashlib.sha256).hexdigest()

        if hmac.compare_digest(manifest.digital_signature, expected_sig):
            return True, "SIGNATURE_VALID: Authentic digital signature verified"
        else:
            return False, "SIGNATURE_INVALID: Manifest has been modified or signature is forged!"

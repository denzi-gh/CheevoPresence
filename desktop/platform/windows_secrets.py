"""Windows API-key protection helpers."""

import base64
import ctypes
import os

from desktop.core.constants import APP_NAME


class DataBlob(ctypes.Structure):
    """Mirror the Win32 DATA_BLOB struct used by DPAPI."""

    _fields_ = [
        ("cbData", ctypes.c_uint),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _blob_from_bytes(data):
    """Wrap Python bytes in a DATA_BLOB plus a keepalive buffer."""
    if not data:
        return DataBlob(), None
    buffer = ctypes.create_string_buffer(data)
    return DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def protect_api_key(value):
    """Encrypt the API key for storage, using DPAPI on Windows."""
    if not value:
        return ""

    raw = value.encode("utf-8")
    if os.name != "nt":
        return base64.b64encode(raw).decode("ascii")

    input_blob, _keepalive = _blob_from_bytes(raw)
    output_blob = DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(ctypes.byref(input_blob), APP_NAME, None, None, None, 0, ctypes.byref(output_blob)):
        raise OSError("Could not protect the API key.")

    try:
        protected = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return base64.b64encode(protected).decode("ascii")
    finally:
        if output_blob.pbData:
            kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))


def unprotect_api_key(value):
    """Decrypt a previously stored API key back into plain text."""
    if not isinstance(value, str) or not value:
        return ""

    try:
        raw = base64.b64decode(value)
    except (ValueError, TypeError):
        return ""

    if os.name != "nt":
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return ""

    input_blob, _keepalive = _blob_from_bytes(raw)
    output_blob = DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)):
        return ""

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData).decode("utf-8")
    except UnicodeDecodeError:
        return ""
    finally:
        if output_blob.pbData:
            kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))

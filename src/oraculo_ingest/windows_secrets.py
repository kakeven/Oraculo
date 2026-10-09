"""Proteção de credenciais locais com DPAPI do usuário do Windows."""

from __future__ import annotations

import ctypes
from ctypes import wintypes


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _transform(payload: bytes, *, decrypt: bool) -> bytes:
    if not payload:
        raise ValueError("Credencial vazia.")
    source_buffer = ctypes.create_string_buffer(payload)
    source = _Blob(len(payload), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = _Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.restype = wintypes.BOOL
    function.argtypes = (
        [ctypes.POINTER(_Blob), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(_Blob),
         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        if decrypt else
        [ctypes.POINTER(_Blob), ctypes.c_wchar_p, ctypes.POINTER(_Blob),
         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    )
    if decrypt:
        ok = function(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result))
    else:
        ok = function(ctypes.byref(source), "Oráculo ChatGPT", None, None, None, 0,
                      ctypes.byref(result))
    if not ok:
        raise OSError(ctypes.get_last_error(), "O Windows não conseguiu proteger ou ler a credencial.")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel32.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


def protect(payload: bytes) -> bytes:
    return _transform(payload, decrypt=False)


def unprotect(payload: bytes) -> bytes:
    return _transform(payload, decrypt=True)

"""
taskbar_utils.py
Set Windows taskbar 'Pin' relaunch properties on the Flet UI window.

When Flet runs, the visible window is owned by flet.exe (a subprocess).
Windows pins that process, so clicking the pin would launch flet.exe
standalone (blank window).  Calling setup_taskbar_relaunch() sets:
  • PKEY_AppUserModel_ID                      → groups with Memento.App
  • PKEY_AppUserModel_RelaunchCommand         → Memento.exe path
  • PKEY_AppUserModel_RelaunchDisplayNameResource → "Memento"
so the taskbar pin always relaunches Memento.exe instead.
"""

import ctypes
import ctypes.wintypes
import struct
import threading
import time
import sys


def setup_taskbar_relaunch(window_title: str, relaunch_cmd: str,
                            app_id: str = "Memento.App") -> None:
    """Spawn a daemon thread that patches the Flet window's taskbar properties."""
    if sys.platform != "win32":
        return
    threading.Thread(
        target=_worker,
        args=(window_title, relaunch_cmd, app_id),
        daemon=True,
        name="TaskbarRelaunch",
    ).start()


# ── internals ──────────────────────────────────────────────────────────────────

def _worker(title: str, relaunch_cmd: str, app_id: str) -> None:
    user32 = ctypes.windll.user32
    # Wait up to 15 s for a window with the matching title
    hwnd = 0
    for _ in range(30):
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            break
        time.sleep(0.5)
    if not hwnd:
        return
    try:
        _apply(hwnd, relaunch_cmd, app_id)
    except Exception:
        pass


def _apply(hwnd: int, relaunch_cmd: str, app_id: str) -> None:
    shell32 = ctypes.windll.shell32

    # IID_IPropertyStore = {886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}
    _IID = (ctypes.c_byte * 16)(*struct.pack(
        "<IHH8B",
        0x886D8EEB, 0x8CF2, 0x4446,
        0x8D, 0x02, 0xCD, 0xBA, 0x1D, 0xBD, 0xCF, 0x99,
    ))

    pps = ctypes.c_void_p(0)
    hr = shell32.SHGetPropertyStoreForWindow(
        hwnd, ctypes.byref(_IID), ctypes.byref(pps)
    )
    if hr != 0 or not pps:
        return

    # IPropertyStore vtable layout (indices):
    # 0 QueryInterface, 1 AddRef, 2 Release, 3 GetCount,
    # 4 GetAt, 5 GetValue, 6 SetValue, 7 Commit
    vtbl = ctypes.cast(
        ctypes.cast(pps, ctypes.POINTER(ctypes.c_void_p))[0],
        ctypes.POINTER(ctypes.c_void_p),
    )

    _FN_SetValue = ctypes.WINFUNCTYPE(
        ctypes.HRESULT,
        ctypes.c_void_p,  # this
        ctypes.c_void_p,  # REFPROPERTYKEY
        ctypes.c_void_p,  # REFPROPVARIANT
    )
    _FN_Simple = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)
    _FN_ULong  = ctypes.WINFUNCTYPE(ctypes.c_ulong,  ctypes.c_void_p)

    _SetValue = _FN_SetValue(vtbl[6])
    _Commit   = _FN_Simple(vtbl[7])
    _Release  = _FN_ULong(vtbl[2])

    # AppUserModel GUID = {9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}
    _GUID = struct.pack(
        "<IHH8B",
        0x9F4C2855, 0x9F79, 0x4B39,
        0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3,
    )

    def _set(pid: int, value: str) -> None:
        # PROPERTYKEY = 16-byte GUID + 4-byte PID (total 20 bytes)
        pkey = (ctypes.c_byte * 20)(*_GUID, *struct.pack("<I", pid))
        # PROPVARIANT (16 bytes): vt(2) + pad(6) + pwszVal(8)
        # VT_LPWSTR = 31
        buf  = ctypes.create_unicode_buffer(value)
        pvar = (ctypes.c_byte * 16)()
        # Write vt at offset 0
        ctypes.cast(pvar, ctypes.POINTER(ctypes.c_ushort))[0] = 31
        # Write pointer at offset 8 (c_size_t index [1] on 64-bit = offset 8)
        ctypes.cast(pvar, ctypes.POINTER(ctypes.c_size_t))[1] = \
            ctypes.cast(buf, ctypes.c_void_p).value
        _SetValue(
            pps,
            ctypes.cast(pkey, ctypes.c_void_p),
            ctypes.cast(pvar, ctypes.c_void_p),
        )

    _set(5, app_id)       # PKEY_AppUserModel_ID
    _set(2, relaunch_cmd) # PKEY_AppUserModel_RelaunchCommand
    _set(4, "Memento")    # PKEY_AppUserModel_RelaunchDisplayNameResource

    _Commit(pps)
    _Release(pps)

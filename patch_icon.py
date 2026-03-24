"""
patch_icon.py
Replaces the main application icon (RT_GROUP_ICON + RT_ICON) inside a Windows
EXE/binary using the Windows resource-update API (no extra dependencies).

Usage:
    python patch_icon.py <exe_path> <ico_path>
"""

import ctypes
import ctypes.wintypes
import struct
import sys
import os

RT_ICON       = 3
RT_GROUP_ICON = 14
LANG_NEUTRAL  = 0

_k32 = ctypes.windll.kernel32
_k32.BeginUpdateResourceW.restype  = ctypes.wintypes.HANDLE
_k32.BeginUpdateResourceW.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]
_k32.UpdateResourceW.restype       = ctypes.c_bool
_k32.UpdateResourceW.argtypes      = [
    ctypes.wintypes.HANDLE,  # hUpdate
    ctypes.c_size_t,         # lpType  (MAKEINTRESOURCE = integer cast to pointer)
    ctypes.c_size_t,         # lpName  (MAKEINTRESOURCE or string)
    ctypes.wintypes.WORD,    # wLanguage
    ctypes.c_void_p,         # lpData
    ctypes.wintypes.DWORD,   # cbData
]
_k32.EndUpdateResourceW.restype    = ctypes.c_bool
_k32.EndUpdateResourceW.argtypes   = [ctypes.wintypes.HANDLE, ctypes.c_bool]


def _parse_ico(path: str) -> list[dict]:
    """Parse an ICO file and return a list of image entry dicts."""
    with open(path, "rb") as f:
        data = f.read()
    _reserved, _type, count = struct.unpack_from("<HHH", data, 0)
    entries = []
    for i in range(count):
        off = 6 + i * 16
        bw, bh, cc, _res, planes, bc, size, img_off = struct.unpack_from("<BBBBHHII", data, off)
        entries.append({
            "width":       bw or 256,
            "height":      bh or 256,
            "color_count": cc,
            "planes":      planes or 1,
            "bit_count":   bc,
            "data":        data[img_off: img_off + size],
        })
    return entries


def patch_exe_icon(exe_path: str, ico_path: str) -> None:
    """Replace the icon resources in exe_path with the icon from ico_path."""
    entries = _parse_ico(ico_path)

    # Remove read-only attribute if set (PyInstaller bundles are often read-only)
    import stat
    current_mode = os.stat(exe_path).st_mode
    if not (current_mode & stat.S_IWRITE):
        os.chmod(exe_path, current_mode | stat.S_IWRITE)

    hUpd = _k32.BeginUpdateResourceW(exe_path, False)
    if not hUpd:
        raise OSError(f"BeginUpdateResource failed (error {ctypes.GetLastError()})")

    ok = True
    try:
        # Write individual RT_ICON resources with sequential IDs 1..N
        for idx, e in enumerate(entries, start=1):
            buf = (ctypes.c_char * len(e["data"])).from_buffer_copy(e["data"])
            ok = ok and _k32.UpdateResourceW(
                hUpd, RT_ICON, idx, LANG_NEUTRAL, buf, len(e["data"]))

        # Build and write RT_GROUP_ICON (GRPICONDIR + GRPICONDIRENTRY[])
        grp = struct.pack("<HHH", 0, 1, len(entries))
        for idx, e in enumerate(entries, start=1):
            bw = e["width"]  if e["width"]  < 256 else 0
            bh = e["height"] if e["height"] < 256 else 0
            grp += struct.pack(
                "<BBBBHHIH",
                bw, bh, e["color_count"], 0,
                e["planes"], e["bit_count"],
                len(e["data"]),
                idx,
            )
        grp_buf = (ctypes.c_char * len(grp)).from_buffer_copy(grp)
        ok = ok and _k32.UpdateResourceW(
            hUpd, RT_GROUP_ICON, 1, LANG_NEUTRAL, grp_buf, len(grp))

    finally:
        _k32.EndUpdateResourceW(hUpd, not ok)   # discard on failure

    if not ok:
        raise OSError(f"UpdateResource failed (error {ctypes.GetLastError()})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: patch_icon.py <exe_path> <ico_path>")
        sys.exit(1)
    exe, ico = sys.argv[1], sys.argv[2]
    print(f"  Patching icon in {os.path.basename(exe)} ...")
    patch_exe_icon(exe, ico)
    print("  Done.")

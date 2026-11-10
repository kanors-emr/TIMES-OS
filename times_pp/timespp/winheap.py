# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows's process heap: which one this process runs on, and how to put a copy of the interpreter on the Segment Heap.

On Windows DuckDB allocates from the process heap (its module links the C runtime statically: HeapAlloc on
GetProcessHeap()). The default heap (the NT heap) makes the preprocessor about twice as slow as on Linux; the Segment
Heap brings it to Linux speed. The heap
type is read from the executable's application manifest, so `TIMES.py setup` makes a copy of the interpreter
whose manifest asks for the Segment Heap (Windows 10 2004 or newer; no administrator rights, no registry change).

Standard library only: TIMES.py loads this file by its path, before the venv's packages are known.

    python winheap.py                show the heap of this process
    python winheap.py selftest       the heap of this process and of a multiprocessing worker, and DuckDB's version (JSON)
    python winheap.py show <exe>     the application manifest of <exe>
    python winheap.py segheap <exe>  add <heapType>SegmentHeap</heapType> to the manifest of <exe>, IN PLACE: on a
                                     copy only, never on an installed interpreter
"""
import os, sys

WIN = os.name == "nt"
SEGMENT = 0xDDEEDDEE        # the 4 bytes at offset 0x10 of a Segment Heap (M. Yason, "Windows 10 Segment Heap
                            # Internals", Black Hat USA 2016); the NT heap has 0xFFEEFFEE there


def heap():
    """'segment' (Segment Heap) or 'nt' (the NT heap) for this process; None when not on Windows."""
    if not WIN:
        return None
    import ctypes
    k = ctypes.windll.kernel32
    k.GetProcessHeap.restype = ctypes.c_void_p
    return "segment" if ctypes.c_uint32.from_address(k.GetProcessHeap() + 0x10).value == SEGMENT else "nt"


# ------------------------------------------------------------------------------------------------------------------
# the application manifest (RT_MANIFEST, id 1), with the Windows API only
RT_MANIFEST, ID = 24, 1
NS = "http://schemas.microsoft.com/SMI/2020/WindowsSettings"
BLOCK = (f'<application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>'
         f'<heapType xmlns="{NS}">SegmentHeap</heapType></windowsSettings></application>')


def _kernel32():
    import ctypes, ctypes.wintypes as W
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.LoadLibraryExW.restype = W.HMODULE
    k.LoadLibraryExW.argtypes = [W.LPCWSTR, W.HANDLE, W.DWORD]
    k.FindResourceW.restype = W.HANDLE
    k.FindResourceW.argtypes = [W.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
    k.LoadResource.restype = W.HANDLE
    k.LoadResource.argtypes = [W.HMODULE, W.HANDLE]
    k.LockResource.restype = ctypes.c_void_p
    k.LockResource.argtypes = [W.HANDLE]
    k.SizeofResource.restype = W.DWORD
    k.SizeofResource.argtypes = [W.HMODULE, W.HANDLE]
    k.FreeLibrary.argtypes = [W.HMODULE]
    k.BeginUpdateResourceW.restype = W.HANDLE
    k.BeginUpdateResourceW.argtypes = [W.LPCWSTR, W.BOOL]
    k.UpdateResourceW.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p, W.WORD, ctypes.c_void_p, W.DWORD]
    k.EndUpdateResourceW.argtypes = [W.HANDLE, W.BOOL]
    return k


def manifest(exe):
    """The application manifest of `exe` (text), or None if it has none."""
    import ctypes
    k = _kernel32()
    h = k.LoadLibraryExW(exe, None, 0x2)                   # LOAD_LIBRARY_AS_DATAFILE
    if not h:
        raise OSError(ctypes.get_last_error(), f"cannot open {exe}")
    try:
        r = k.FindResourceW(h, ID, RT_MANIFEST)
        if not r:
            return None
        return ctypes.string_at(k.LockResource(k.LoadResource(h, r)), k.SizeofResource(h, r)).decode("utf-8")
    finally:
        k.FreeLibrary(h)


def add_segment_heap(exe):
    """Add heapType SegmentHeap to the manifest of `exe`, in place (a copy: the change removes its signature).
    Nothing to do when it is there already."""
    import ctypes
    m = manifest(exe)
    if m is None:
        raise ValueError(f"{exe} has no application manifest")
    if "heapType" in m:
        return
    if "<windowsSettings>" in m:                            # add to the existing block
        m = m.replace("<windowsSettings>", f'<windowsSettings><heapType xmlns="{NS}">SegmentHeap</heapType>', 1)
    else:
        i = m.rindex("</assembly>")
        m = m[:i] + BLOCK + m[i:]
    b = m.encode("utf-8")
    k = _kernel32()
    h = k.BeginUpdateResourceW(exe, False)
    if not h:
        raise OSError(ctypes.get_last_error(), f"cannot change {exe}")
    buf = ctypes.create_string_buffer(b, len(b))
    if not k.UpdateResourceW(h, RT_MANIFEST, ID, 0x409, buf, len(b)):
        err = ctypes.get_last_error()
        k.EndUpdateResourceW(h, True)
        raise OSError(err, f"cannot change the manifest of {exe}")
    if not k.EndUpdateResourceW(h, False):
        raise OSError(ctypes.get_last_error(), f"cannot write {exe}")


def image():
    """The program file of this process (not sys.executable, which a venv's launcher sets to its own name)."""
    import ctypes, ctypes.wintypes as W
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = W.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)]
    buf = ctypes.create_unicode_buffer(32768)
    n = W.DWORD(len(buf))
    return buf.value if k.QueryFullProcessImageNameW(k.GetCurrentProcess(), 0, buf, ctypes.byref(n)) else None


def _probe(_):
    return heap(), image()


def selftest():
    """What TIMES.py setup checks in the interpreter copy, as one line of JSON: the heap of this process and of a
    worker process started as the DD reader starts its workers (multiprocessing), and that DuckDB imports."""
    import json, multiprocessing
    out = {"heap": heap(), "image": image(), "version": sys.version.split()[0]}
    try:
        import duckdb
        out["duckdb"] = duckdb.__version__
    except Exception as e:
        out["duckdb_error"] = f"{type(e).__name__}: {e}"
    try:
        with multiprocessing.get_context("spawn").Pool(1) as p:
            out["worker_heap"], out["worker_image"] = p.map(_probe, [0])[0]
    except Exception as e:
        out["worker_error"] = f"{type(e).__name__}: {e}"
    print(json.dumps(out))


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print(f"{sys.executable}: {heap() or 'not Windows'}")
    elif sys.argv[1] == "selftest":
        selftest()
    elif sys.argv[1] == "show":
        print(manifest(sys.argv[2]))
    elif sys.argv[1] == "segheap":
        add_segment_heap(sys.argv[2])
        print(manifest(sys.argv[2]))

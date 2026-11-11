"""Fast fresh-chip SID objects from the exact official VICE3.10 reSID source.

Settings match installed VICE defaults: MOS6581, resampling,90% Nyquist
passband,97% gain,500mV filter bias, internal and external filters enabled.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tarfile

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "results/channel-fit-2/resid-core"
ARCHIVE = OUT / "vice-3.10.tar.gz"
OFFICIAL_URL = "https://downloads.sourceforge.net/project/vice-emu/releases/vice-3.10.tar.gz"
EXPECTED_SHA = "8e5bac18cbcb9f192380ad3ef881f8790f5b75c41d7b3da65d831985d864d6d1"
SOURCE = OUT / "vice-3.10/src/resid"
LIBRARY = OUT / "libchannel_resid.dylib"
CLOCK = 985248
_LIB = None


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_library() -> dict:
    if not ARCHIVE.exists() or sha(ARCHIVE) != EXPECTED_SHA:
        raise RuntimeError(f"Missing or wrong official VICE3.10 archive; expected{EXPECTED_SHA}")
    with tarfile.open(ARCHIVE) as archive:
        selected = [m for m in archive.getmembers() if "/src/resid/" in m.name or m.name in (
            "vice-3.10/COPYING", "vice-3.10/src/sid/resid.cc", "vice-3.10/src/sid/sid.h")]
        for member in selected:
            archive.extract(member, OUT, filter="data")
    header = (SOURCE / "siddefs.h.in").read_text()
    config = {"RESID_INLINING": "1", "RESID_INLINE": "inline", "RESID_BRANCH_HINTS": "1",
              "NEW_8580_FILTER": "1", "HAVE_BOOL": "1", "HAVE_BUILTIN_EXPECT": "1", "HAVE_LOG1P": "1"}
    for key, value in config.items():
        header = header.replace("@" + key + "@", value)
    (SOURCE / "siddefs.h").write_text(header)
    units = ["sid.cc", "voice.cc", "wave.cc", "envelope.cc", "filter8580new.cc", "dac.cc", "extfilt.cc", "pot.cc", "version.cc"]
    command = ["clang++", "-std=c++17", "-O3", "-DNDEBUG", '-DVERSION="1.0-pre2"',
               "-fPIC", "-dynamiclib", "-I", str(SOURCE), str(HERE / "channel_resid.cpp"),
               *[str(SOURCE / name) for name in units], "-o", str(LIBRARY)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=90)
    (OUT / "build.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode:
        raise RuntimeError(f"reSID compilation failed; inspect{OUT / 'build.log'}")
    provenance = {"official_source_url": OFFICIAL_URL, "archive_sha256": EXPECTED_SHA,
                  "installed_formula": "/opt/homebrew/Cellar/vice/3.10/.brew/vice.rb",
                  "license": "GPL-2.0-or-later; original source/COPYING retained",
                  "source_modifications": "No emulator algorithm changes; generated siddefs.h compiler configuration only.",
                  "configuration": config, "compiler_command": command, "library_sha256": sha(LIBRARY),
                  "source_sha256": {name: sha(SOURCE / name) for name in units},
                  "bridge_sha256": {name: sha(HERE / name) for name in ("channel_resid.cpp", "channel_resid.py")},
                  "settings": {"model": "MOS6581", "sampling": "SAMPLE_RESAMPLE", "clock_hz": CLOCK,
                               "passband_percent": 90, "gain_percent": 97, "filter_bias_mv": 500,
                               "internal_filter": True, "external_filter": True,
                               "voice_mask": 7, "external_input": 0},
                  "installed_feature_match": "x64sc -features reports HAVE_NEW_8580_FILTER=yes; the same source variant is compiled."}
    (OUT / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return provenance


def _library():
    global _LIB
    if _LIB is None:
        if not LIBRARY.exists():
            build_library()
        _LIB = ctypes.CDLL(str(LIBRARY))
        _LIB.c64_resid_create.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
        _LIB.c64_resid_create.restype = ctypes.c_void_p
        _LIB.c64_resid_destroy.argtypes = [ctypes.c_void_p]
        _LIB.c64_resid_write.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        _LIB.c64_resid_clock.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int16), ctypes.c_int]
        _LIB.c64_resid_clock.restype = ctypes.c_int
    return _LIB


class SID:
    def __init__(self, rate: int, bias_mv: float = 500):
        self.rate, self.bias_mv = rate, bias_mv
        self.library = _library()
        self.handle = None
        self.buffer = np.empty(4096, dtype=np.int16)
        self.reset()

    def reset(self):
        # Native SID::reset preserves some oscillator state. A new instance is
        # the isolation boundary, including between repeated optimizer calls.
        if self.handle:
            self.library.c64_resid_destroy(self.handle)
        self.handle = self.library.c64_resid_create(float(self.rate), float(CLOCK), self.bias_mv)
        if not self.handle:
            raise RuntimeError("Unable to initialize the VICE reSID core")

    def write(self, reg: int, value: int):
        if not 0 <= reg <= 24 or not 0 <= value <= 255:
            raise ValueError("SID register write outside writable range")
        self.library.c64_resid_write(self.handle, int(reg), int(value))

    def clock(self, cycles: int):
        if cycles < 0 or cycles > 2_000_000_000:
            raise ValueError("Invalid SID clock interval")
        if not cycles:
            return ()
        capacity = math.ceil(cycles * self.rate / CLOCK) + 16
        if capacity > len(self.buffer):
            self.buffer = np.empty(capacity, dtype=np.int16)
        count = self.library.c64_resid_clock(self.handle, int(cycles),
                                            self.buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)), len(self.buffer))
        if count < 0:
            raise RuntimeError(f"VICE reSID clock failed:{count}")
        return self.buffer[:count].copy()

    def __del__(self):
        handle = getattr(self, "handle", None)
        if handle:
            self.library.c64_resid_destroy(handle)
            self.handle = None


def make_sid(rate: int) -> SID:
    return SID(rate)


if __name__ == "__main__":
    print(json.dumps(build_library(), indent=2))

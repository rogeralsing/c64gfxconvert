"""The single supported VICE playback and capture profile."""
from __future__ import annotations

PAL_CLOCK = 985248
RATE = 22050
MODEL = "PAL MOS8580 + digiboost"
PROFILE = {"machine": "PAL C64", "sid_engine": 1, "sid_model": 2,
           "digiboost": True, "resampling": 2, "sample_rate": RATE}


def vice_command() -> list[str]:
    return ["/opt/homebrew/bin/x64sc", "-default", "-pal",
            "-sidengine", str(PROFILE["sid_engine"]),
            "-sidmodel", str(PROFILE["sid_model"]),
            "-residsamp", str(PROFILE["resampling"]), "-soundrate", str(RATE),
            "-soundoutput", "1", "-soundvolume", "100"]

#!/usr/bin/env python3
"""Unchanged True Paint MCI decoder from mci-viewer/sine-data.py."""

import numpy as np


def decode_mci(data):
    if len(data) != 19434 or data[:2] != b"\x00\x9c":
        raise ValueError("Expected an uncompressed 19,434-byte True Paint MCI.")
    background = data[1002]
    shared = np.frombuffer(data[18434:19434], dtype=np.uint8)
    if background > 15 or np.any(shared > 15):
        raise ValueError("MCI colors must use C64 indices 0–15.")
    phases = np.empty((2, 200, 160), dtype=np.uint8)
    for phase in range(2):
        screen_offset = 2 if phase == 0 else 17410
        bitmap_offset = 1026 if phase == 0 else 9218
        for y in range(200):
            for column in range(40):
                tile = y // 8 * 40 + column
                screen = data[screen_offset + tile]
                colors = [background, screen >> 4, screen & 15, int(shared[tile])]
                bits = data[bitmap_offset + tile * 8 + y % 8]
                for pixel in range(4):
                    phases[phase, y, column * 4 + pixel] = colors[bits >> (6 - pixel * 2) & 3]
    return background, phases

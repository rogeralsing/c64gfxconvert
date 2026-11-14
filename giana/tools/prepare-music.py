#!/usr/bin/env python3
"""Extract the complete original Giana SID player and scores without mutation."""

import hashlib
import json
from pathlib import Path


ASSETS = Path(__file__).resolve().parents[1] / "assets"
SOURCE_SHA256 = "014764e6ee11df4b458c6b30e235ea639d702bd56766a87b5e90d4737558b1c8"
MODULE_SHA256 = "09ed883e8991e224604eda00b1ff3c7219f815f4e0de4b033ecd1d2fb5bf3c4c"
SID_MODULE_ADDRESS = 0x71e3
ORIGINAL_ADDRESS = 0x41c0
ORIGINAL_END = 0x5fdd
MODULE_BYTES = ORIGINAL_END - ORIGINAL_ADDRESS


def main():
    source = (ASSETS / "music-source.sid").read_bytes()
    assert hashlib.sha256(source).hexdigest() == SOURCE_SHA256
    assert source[:4] == b"RSID"
    payload_offset = int.from_bytes(source[6:8], "big")
    load_address = int.from_bytes(source[8:10], "big")
    if load_address == 0:
        load_address = int.from_bytes(source[payload_offset:payload_offset + 2], "little")
        payload_offset += 2
    first = payload_offset + SID_MODULE_ADDRESS - load_address
    assert first >= payload_offset
    module = source[first:first + MODULE_BYTES]
    assert len(module) == 7709 and hashlib.sha256(module).hexdigest() == MODULE_SHA256
    assert module[:12] == bytes.fromhex("4c9e434c46434c87494ce649")
    (ASSETS / "music-original.bin").write_bytes(module)
    assembly = [
        "// Complete original native SID driver and score data; no byte patches.",
        ".const MUSIC_LOAD = $41c0", ".const MUSIC_BYTES = 7709",
        ".const MUSIC_INIT = $41c3", ".const MUSIC_SELECT = $41c9", ".const MUSIC_PLAY = $41c0",
        ".const MUSIC_LEVEL1_CUE = 1", ".const MUSIC_SOURCE_SUBTUNE = 3",
        ".const MUSIC_ZERO_PAGE_FIRST = $a4", ".const MUSIC_ZERO_PAGE_LAST = $b9",
        '.var originalGameMusicFile = LoadBinary("music-original.bin")',
        "musicOriginal:", "    .fill originalGameMusicFile.getSize(), originalGameMusicFile.get(i)",
        "musicOriginalEnd:",
        '.assert "Music remains at its original address", musicOriginal, MUSIC_LOAD',
        '.assert "Complete original music module", musicOriginalEnd - musicOriginal, MUSIC_BYTES',
        "",
    ]
    (ASSETS / "music.asm").write_text("\n".join(assembly))
    receipt = {
        "source_file": "music-source.sid", "source_sha256": SOURCE_SHA256,
        "source_bytes": len(source), "source_subtune_one_based": 3,
        "sid_payload_load_address": load_address, "module_source_sid_address": SID_MODULE_ADDRESS,
        "module_source_file_offset": first,
        "module_file": "music-original.bin", "module_sha256": MODULE_SHA256,
        "module_bytes": len(module), "runtime_start": ORIGINAL_ADDRESS,
        "runtime_end_exclusive": ORIGINAL_END,
        "module_byte_mutations": 0,
        "level1_internal_cue": 1, "selector_carry": "clear",
        "init_vector": 0x41c3, "select_vector": 0x41c9, "play_vector": 0x41c0,
        "init_routine": 0x4346, "select_routine": 0x49e6, "play_routine": 0x439e,
        "zero_page_workspace": [0xa4, 0xb9],
        "original_program_sha256": "0f1a720961fa52102fcfd52e46e40df07e5e307328ad087d55cc00506f904880",
        "original_level1_cue_table_address": 0x152a,
        "scope": "complete native player and score module; score-controlled looping, no excerpt or PCM",
        "source_metadata": {name: source[offset:offset + 32].split(b"\0", 1)[0].decode("latin1")
                            for name, offset in (("title", 0x16), ("author", 0x36), ("released", 0x56))},
    }
    (ASSETS / "music-import.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("Original Giana music: 7,709 unchanged bytes, full player/scores; Level 1 cue 1, SID subtune 3.")


if __name__ == "__main__":
    main()

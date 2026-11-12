#!/usr/bin/env python3
"""Reproduce the verified Dance Nation relocation without build dependencies."""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def prepare(output):
    manifest = json.loads((HERE / "assets" / "Dance_Nation-relocation.json").read_text())
    source = (HERE / "assets" / manifest["source_file"]).read_bytes()
    if hashlib.sha256(source).hexdigest() != manifest["source_sha256"]:
        raise ValueError("Dance Nation source does not match the verified relocation")

    relocated = bytearray(source)
    payload_offset = manifest["payload_offset"]
    page_delta = (manifest["relocated_load"] - manifest["original_load"]) // 256
    zero_page_delta = manifest["relocated_zero_page"][0] - manifest["original_zero_page"][0]
    for offset, original, replacement in manifest["header_patches"]:
        if relocated[offset] != original:
            raise ValueError("Dance Nation header does not match the relocation manifest")
        relocated[offset] = replacement
    for offset in manifest["payload_msb_offsets"]:
        relocated[payload_offset + offset] = (source[payload_offset + offset] + page_delta) & 255
    for offset in manifest["payload_zero_page_offsets"]:
        relocated[payload_offset + offset] = (source[payload_offset + offset] + zero_page_delta) & 255
    if hashlib.sha256(relocated).hexdigest() != manifest["relocated_sha256"]:
        raise ValueError("Dance Nation relocation differs from the verified sidreloc output")

    payload = relocated[payload_offset:]
    if len(payload) != manifest["payload_length"]:
        raise ValueError("Dance Nation payload length does not match the relocation manifest")
    constants = {
        "LOAD": manifest["relocated_load"],
        "INIT": int.from_bytes(relocated[10:12], "big"),
        "PLAY": int.from_bytes(relocated[12:14], "big"),
        "START_SONG": int.from_bytes(relocated[16:18], "big") - 1,
        "ZP_LOW": manifest["relocated_zero_page"][0],
        "ZP_HIGH": manifest["relocated_zero_page"][1],
        "SIZE": len(payload),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "Dance_Nation-b000.sid").write_bytes(relocated)
    (output / "music.bin").write_bytes(payload)
    (output / "music.asm").write_text(
        "// Dance Nation by Richard Bayliss, 2002 The New Dimension.\n"
        + "".join(f".const MUSIC_{key} = {value}\n" for key, value in constants.items())
    )
    receipt = {
        **manifest["tune"],
        "source_url": manifest["source_url"],
        "source_sha256": manifest["source_sha256"],
        "relocated_sha256": manifest["relocated_sha256"],
        "payload_bytes": len(payload),
        "load": constants["LOAD"],
        "init": constants["INIT"],
        "play": constants["PLAY"],
        "zero_page": manifest["relocated_zero_page"],
        "relocation_tool": manifest["tool"],
        "independent_verification": manifest["independent_verification"],
    }
    (output / "music.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    prepare(HERE / "build")

#!/usr/bin/env python3
"""Build the isolated original-film clip with the existing native AV player.

Inputs are one fixed 256-character font, sixty screen matrices and the matching
six-second original soundtrack. The accepted GIF player and release stay intact.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np


HERE = Path(__file__).resolve().parents[1]
DEFAULT_ASSETS = HERE / "work/original-c64/assets"
DEFAULT_OUTPUT = HERE / "work/original-c64/player-final"
DEFAULT_AUDIO = HERE / "work/original-calibration/source/original-audio.wav"
DEFAULT_RUNTIME = Path(__file__).resolve().parent / "player.asm"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def module(path: Path, name: str):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def allocate(movie_bytes: int, packed_bytes: int) -> tuple[list, list, list, dict]:
    """Use the runtime's existing $7000->$7900 movie gap and safe PCM arenas."""
    movie_chunks = []
    cursor = 0
    for first, end in ((0x2800, 0x7000), (0x7900, 0xD000)):
        count = min(end - first, movie_bytes - cursor)
        if count:
            movie_chunks.append(dict(address=first, offset=cursor, bytes=count))
            cursor += count
    if cursor != movie_bytes:
        raise ValueError(f"Movie exceeds existing safe movie arenas: {movie_bytes} bytes")
    jitter = [dict(page=page, address=page * 256,
                   bytes=5 + (page - 0x70 + 1) // 2, delta=page - 0x70)
              for page in range(0x70, 0x79)]
    occupied = [(chunk["address"], chunk["address"] + chunk["bytes"])
                for chunk in movie_chunks + jitter]
    ranges = [(0x0C00, 0x1000), (0x1B00, 0x1C00), (0x1E00, 0x2000),
              (0x2800, 0xD000), (0xE000, 0xFFFA)]
    for used_first, used_end in sorted(occupied):
        free = []
        for first, end in ranges:
            if used_end <= first or used_first >= end:
                free.append((first, end))
            else:
                if first < used_first:
                    free.append((first, used_first))
                if used_end < end:
                    free.append((used_end, end))
        ranges = free
    available = sum(end - first for first, end in ranges)
    memory = dict(movieBytes=movie_bytes, packedAudioBytes=packed_bytes,
                  pcmAvailableBytes=available, spareDataBytes=available - packed_bytes,
                  movieBudgetWithThisAudio=movie_bytes + available - packed_bytes,
                  movieGapStart=0x7000, movieGapEnd=0x7900,
                  ioExcludedStart=0xD000, ioExcludedEnd=0xE000)
    print(json.dumps(dict(memoryFit=available >= packed_bytes, memory=memory)), flush=True)
    if available < packed_bytes:
        raise ValueError(f"Exact clip needs {packed_bytes - available} more safe bytes; "
                         f"movie={movie_bytes}, PCM={packed_bytes}")
    pcm_chunks, cursor = [], 0
    for first, end in ranges:
        count = min(end - first, packed_bytes - cursor)
        if count:
            pcm_chunks.append(dict(address=first, offset=cursor, bytes=count))
            cursor += count
        if cursor == packed_bytes:
            break
    if cursor != packed_bytes:
        raise ValueError("Packed audio allocation dropped source bytes")
    return movie_chunks, pcm_chunks, jitter, memory


def build(output: Path, assets: Path, source: Path, loop: bool = True,
          runtime: Path = DEFAULT_RUNTIME) -> dict:
    output, assets, source, runtime = (path.resolve() for path in (output, assets, source, runtime))
    output.mkdir(parents=True, exist_ok=True)
    inputs = [assets / "font.bin", assets / "screen.frames", assets / "manifest.json", source, runtime]
    protected = {str(path): sha(path.read_bytes()) for path in inputs}
    original_manifest = (assets / "manifest.json").read_bytes()
    source_manifest = json.loads(original_manifest)
    for filename, field in (("font.bin", "fontSha256"), ("screen.frames", "screenSha256")):
        expected_hash = source_manifest.get(field, source_manifest.get("hashes", {}).get(filename))
        if expected_hash and protected[str(assets / filename)] != expected_hash:
            raise ValueError(f"Prepared asset does not match its manifest: {filename}")
    if source_manifest.get("sourceAudioSha256", protected[str(source)]) != protected[str(source)]:
        raise ValueError("Original soundtrack does not match the prepared film's source audio")
    frame_count, fps, duration = (source_manifest[key] for key in
                                  ("frameCount", "fps", "durationSeconds"))
    if (frame_count, fps, duration) != (60, 10, 6):
        raise ValueError("This unchanged AV runtime expects sixty frames at 10 fps over six seconds")
    audio = output / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    component = module(HERE / "build.py", "original_movie_audio_component")
    component.prepare(source, audio)
    prep = json.loads((audio / "preparation.json").read_text())
    packed = (audio / "packed.bin").read_bytes()
    expected_audio = (audio / "expected-input.bin").read_bytes()
    if (prep["sampleCount"], len(packed), prep["period"]) != (46917, 23552, 126):
        raise ValueError("Original soundtrack must retain the complete six-second native clock")
    assert sha(expected_audio) == prep["inputSha256"]
    assert sha(packed) == prep["packedSha256"]
    assert prep["sourceSha256"] == protected[str(source)]
    font = (assets / "font.bin").read_bytes()
    raw_screens = (assets / "screen.frames").read_bytes()
    if len(font) != 2048 or len(raw_screens) != frame_count * 1000:
        raise ValueError("Expected one 2048-byte font and sixty complete 40x25 screens")
    screens = np.frombuffer(raw_screens, np.uint8).reshape(frame_count, 1000)
    mono = module(HERE / "screen_codec.py", "original_movie_screen_codec")
    packets, packet_stats = [], []
    for frame in range(frame_count):
        packet, stats = mono.encode_screen(screens[frame - 1], screens[frame])
        assert np.array_equal(mono.decode_screen(packet, screens[frame - 1]), screens[frame])
        packets.append(packet)
        packet_stats.append(stats)
    movie = b"".join(packets)
    keyframe = mono.encode_screen(np.zeros(1000, np.uint8), screens[0])[0]
    assert np.array_equal(mono.decode_screen(keyframe, np.zeros(1000, np.uint8)), screens[0])
    if len(keyframe) > 768:
        raise ValueError(f"Exact keyframe needs {len(keyframe)} bytes; fixed arena allows 768")
    movie_chunks, pcm_chunks, jitter, memory = allocate(len(movie), len(packed))
    memory["keyframeBytes"] = len(keyframe)
    memory["keyframeBudgetBytes"] = 768
    offsets, cursor = [], 0
    for packet in packets:
        offsets.append(cursor)
        cursor += len(packet)

    def movie_address(offset: int) -> int:
        for chunk in movie_chunks:
            if chunk["offset"] <= offset < chunk["offset"] + chunk["bytes"]:
                return chunk["address"] + offset - chunk["offset"]
        raise ValueError(f"Movie offset outside allocated data: {offset}")

    pointers = b"".join(movie_address(offset).to_bytes(2, "little") for offset in offsets)
    deadlines = [round(frame * prep["sampleCount"] / frame_count) for frame in range(frame_count)]
    for filename, raw in (("packed.bin", packed), ("expected-input.bin", expected_audio),
                          ("font.bin", font), ("movie.bin", movie), ("keyframe.bin", keyframe),
                          ("expected-screen.frames", raw_screens), ("frame-pointers.bin", pointers),
                          ("frame-deadlines.bin", b"".join(x.to_bytes(2, "little") for x in deadlines))):
        (output / filename).write_bytes(raw)
    for filename in ("high-lookup.bin", "low-lookup.bin", "target-input.bin"):
        shutil.copyfile(audio / filename, output / filename)
    shutil.copyfile(runtime, output / "gif-av-player.asm")
    config = dict(PACKED_START=pcm_chunks[0]["address"], SAMPLE_COUNT=prep["sampleCount"],
                  PAGE_COUNT=prep["pageCount"], FULL_PAGES=prep["fullPages"], FINAL_VALUES=prep["finalValues"],
                  FRAME_COUNT=frame_count, LOOP=int(loop))
    (output / "config.asm").write_text("\n".join(f".const {key}={value}" for key, value in config.items()) + "\n")
    transitions = ["advance_source_page:", "lda packed_read+2"]
    for before, after in zip(pcm_chunks, pcm_chunks[1:]):
        natural = before["address"] + before["bytes"]
        assert natural & 255 == 0
        if after["address"] != natural:
            transitions += [f"cmp #{natural >> 8}", "bne !next+", f"lda #{after['address'] & 255}",
                            "sta packed_read+1", f"lda #{after['address'] >> 8}",
                            "sta packed_read+2", "rts", "!next:"]
    transitions += ["rts"]
    (output / "source-transitions.asm").write_text("\n".join(transitions) + "\n")
    data = ['.pc=$1800 "Encoded frame zero"', "keyframe_data:", '.import binary "keyframe.bin"',
            "keyframe_end:", '.assert "Keyframe below PCM page",keyframe_end<=$1b00,true',
            '.pc=$1c00 "Nibble lookup high"', "high_lookup:", '.import binary "high-lookup.bin"',
            '.pc=$1d00 "Nibble lookup low"', "low_lookup:", '.import binary "low-lookup.bin"',
            '.pc=$2000 "Fixed movie font"', "font:", '.import binary "font.bin"',
            "font_end:", '.assert "Font bank exact",font_end==$2800,true']
    for chunk in movie_chunks:
        data += [f'.pc=${chunk["address"]:04x} "Movie delta segment"',
                 f'.import binary "movie.bin",{chunk["offset"]},{chunk["bytes"]}']
    for entry in jitter:
        delta = entry["delta"]
        data += [f'.pc=${entry["address"]:04x} "Original distributed jitter entry"', f'.fill {delta // 2},$ea']
        data += [".byte $85,<(restore_a+1)"] if delta % 2 == 0 else [".byte $8d,<(restore_a+1),>(restore_a+1)"]
        data += ["jmp nmi_common"]
    for chunk in pcm_chunks:
        data += [f'.pc=${chunk["address"]:04x} "Packed whistle segment"',
                 f'.import binary "packed.bin",{chunk["offset"]},{chunk["bytes"]}']
    (output / "data.asm").write_text("\n".join(data) + "\n")
    (output / "main.asm").write_text('.var framePointers=LoadBinary("frame-pointers.bin")\n'
                                      '.var frameDeadlines=LoadBinary("frame-deadlines.bin")\n'
                                      '.import source "gif-av-player.asm"\n')
    assembled = subprocess.run(["rtk", "proxy", str(Path.home() / ".local/bin/kickass"), "main.asm",
                                "-odir", str(output), "-o", str(output / "native-image.prg"), "-symbolfile"],
                               cwd=output, text=True, capture_output=True, timeout=60)
    (output / "build.log").write_text(assembled.stdout + assembled.stderr)
    if assembled.returncode:
        raise RuntimeError(assembled.stdout + assembled.stderr)
    labels = {key: int(value, 16) for key, value in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", (output / "main.sym").read_text())}
    save(output / "labels.json", labels)
    native = (output / "native-image.prg").read_bytes()
    load = int.from_bytes(native[:2], "little")
    regions = [dict(name="runtime", address=0x1000, bytes=labels["player_code_end"] - 0x1000),
               dict(name="keyframe", address=0x1800, bytes=len(keyframe)),
               dict(name="lookup-high", address=0x1C00, bytes=256),
               dict(name="lookup-low", address=0x1D00, bytes=256),
               dict(name="font", address=0x2000, bytes=2048)]
    regions += [dict(name="movie", **chunk) for chunk in movie_chunks]
    regions += [dict(name="packed", **chunk) for chunk in pcm_chunks]
    regions += [dict(name="jitter", address=entry["address"], bytes=entry["bytes"]) for entry in jitter]
    ordered = sorted(regions, key=lambda region: region["address"])
    for before, after in zip(ordered, ordered[1:]):
        assert before["address"] + before["bytes"] <= after["address"], (before, after)
    assert load == 0x0801 and load + len(native) - 2 <= 0xFFFA
    for chunks, raw in ((pcm_chunks, packed), (movie_chunks, movie)):
        for chunk in chunks:
            assert native[2 + chunk["address"] - load:2 + chunk["address"] - load + chunk["bytes"]] == raw[
                chunk["offset"]:chunk["offset"] + chunk["bytes"]]
    expected_pixels = [mono.rgba_hash(mono.decode_pixels(screen, font)) for screen in screens]
    assert expected_pixels == source_manifest["expectedDecodedRGBAHashes"], "Prepared original-film pixels changed"
    packer = module(HERE / "pack.py", "original_movie_cold_packer")
    package = packer.package(output / "native-image.prg", output / "player.prg", entry=labels["start"])
    program = (output / "player.prg").read_bytes()
    for path, expected_hash in protected.items():
        assert sha(Path(path).read_bytes()) == expected_hash, f"Input changed during build: {path}"
    result = dict(program=str(output / "player.prg"), program_sha256=sha(program),
                  native_program=str(output / "native-image.prg"), native_sha256=sha(native),
                  source_sha256=sha(runtime.read_bytes()), runtimeSource=str(runtime), symbols=labels, preparation=prep,
                  packedChunks=pcm_chunks, movieChunks=movie_chunks, regions=regions, package=package,
                  stateAddresses=dict(boundary_count=2, boundary_before=3, generated_pages=4,
                                      underruns=5, finished=6, next_buffer=7),
                  film=dict(frameCount=frame_count, sourceFPS=fps, durationSeconds=duration,
                            frontBufferRendering=True, source="Original Steamboat Willie 32–38 s, selected outlines bitmap",
                            sourceManifestSha256=sha(original_manifest), sourceScreenSha256=sha(raw_screens),
                            monoDerivation="Prepared original-film fixed font and screen.frames copied exactly; no runtime image changes",
                            expectedScreenFile="expected-screen.frames", expectedRGBAHashes=expected_pixels,
                            fontAddress=0x2000, fontSha256=sha(font), fontBytes=2048,
                            movieBytes=len(movie), keyframeBytes=len(keyframe),
                            frameAddresses=[movie_address(offset) for offset in offsets], sampleDeadlines=deadlines,
                            synchronization="Direct front-buffer delta begins at each100ms consumed-sample deadline; completion recorded separately",
                            backgroundC64=1, foregroundC64=0, colorBytes=0),
                  audioComponentSha256=sha((HERE / "player.asm").read_bytes()), screenOn=True, loop=loop,
                  entry=labels["start"], nativeEndExclusive=load + len(native) - 2,
                  codeBytes=labels["player_code_end"] - 0x1000, sourceRegions=regions,
                  memory=memory, packetStats=packet_stats, protectedInputSha256=protected,
                  inputsUnchanged=True, nativePlaybackVerified=False)
    save(output / "build.json", result)
    print(json.dumps(dict(program=result["program"], programSha256=result["program_sha256"],
                          codeBytes=result["codeBytes"], nativeEnd=result["nativeEndExclusive"],
                          keyframeBytes=len(keyframe), memory=memory, loop=loop)), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--audio", type=Path, default=DEFAULT_AUDIO)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--no-loop", action="store_true")
    args = parser.parse_args()
    build(args.output, args.assets, args.audio, not args.no_loop, args.runtime)


if __name__ == "__main__":
    main()

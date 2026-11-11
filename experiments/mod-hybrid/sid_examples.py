"""Extract auditable SID instrument seeds from the official GoatTracker pack.

This reads the documented GTS5 data format. It preserves original table rows;
it does not copy the editor/player implementation or claim audio similarity.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "sources/sid-examples"
OUTPUT = HERE / "results/channel-fit-2"
ARCHIVE_URL = "https://sourceforge.net/projects/goattracker2/files/GoatTracker%202/2.77/GoatTracker_2.77.zip/download"


class Reader:
    def __init__(self, data: bytes):
        self.data, self.position = data, 0

    def get(self, count: int = 1) -> bytes:
        result = self.data[self.position:self.position + count]
        if len(result) != count:
            raise ValueError("Truncated GTS5 file")
        self.position += count
        return result

    def byte(self) -> int:
        return self.get()[0]

    def text(self, count: int) -> str:
        return self.get(count).split(b"\0")[0].decode("latin1").strip()


def read_song(path: Path) -> dict:
    data = path.read_bytes()
    reader = Reader(data)
    if reader.get(4) != b"GTS5":
        raise ValueError("Only documented GTS5 files are accepted")
    result = {"file": str(path.resolve()), "sha256": hashlib.sha256(data).hexdigest(),
              "title": reader.text(32), "author": reader.text(32), "copyright": reader.text(32)}
    subtunes = reader.byte()
    for _ in range(subtunes * 3):
        reader.get(reader.byte() + 1)
    instruments = []
    for index in range(reader.byte()):
        values = list(reader.get(9))
        instruments.append({"id": index + 1, "name": reader.text(16),
                            "ad": values[0], "sr": values[1], "table_pointers": values[2:6],
                            "vibrato_delay": values[6], "gate_timer": values[7], "first_wave": values[8]})
    tables = []
    for _ in range(4):
        count = reader.byte()
        left, right = reader.get(count), reader.get(count)
        tables.append(list(zip(left, right)))
    patterns = []
    for _ in range(reader.byte()):
        count = reader.byte()
        values = reader.get(count * 4)
        patterns.append([tuple(values[i:i + 4]) for i in range(0, len(values), 4)])
    if reader.position != len(data):
        raise ValueError(f"Unexpected trailing data in {path.name}")
    result.update(instruments=instruments, tables=tables, pattern_count=len(patterns))
    return result


def reachable_table(table: list, pointer: int, speed: bool = False) -> list[dict]:
    if not pointer:
        return []
    if speed:
        left, right = table[pointer - 1]
        return [{"position": pointer, "left": left, "right": right,
                 "hex": f"{left:02X} {right:02X}"}]
    result, visited = [], set()
    position = pointer
    while position and position not in visited:
        visited.add(position)
        left, right = table[position - 1]
        result.append({"position": position, "left": left, "right": right,
                       "hex": f"{left:02X} {right:02X}"})
        position = right if left == 255 else position + 1
    return result


def frame_program(instrument: dict, tables: list, count: int = 32) -> list[dict]:
    """Expand this selected, command-free table subset after note initialization.

    The first frame is the tracker's first_wave init; table processing starts
    on the following update. Pulse state starts at0 for a standalone seed.
    Vibrato remains a separate documented raw speed-table parameter.
    """
    wp, pp = instrument["table_pointers"][:2]
    control, pulse, relative = instrument["first_wave"], 0, 0
    wave_delay = pulse_remaining = 0
    frames = []
    for frame in range(count):
        if frame:
            if wp:
                left, right = tables[0][wp - 1]
                if left == 255:
                    wp = right
                    if wp:
                        left, right = tables[0][wp - 1]
                if wp:
                    if 1 <= left <= 15:
                        wave_delay += 1
                        if wave_delay > left:
                            wave_delay = 0
                            wp += 1
                    else:
                        if 16 <= left <= 223:
                            control = left
                        elif 224 <= left <= 239:
                            control = left & 15
                        elif left >= 240:
                            raise ValueError("Selected frame seeds must not execute table commands")
                        if right != 128:
                            if right >= 128:
                                raise ValueError("Selected frame seeds must use relative notes")
                            relative = right if right < 96 else right - 128
                        wp += 1
                    if wp and tables[0][wp - 1][0] == 255:
                        wp = tables[0][wp - 1][1]
            if pp:
                left, right = tables[1][pp - 1]
                if left == 255:
                    pp = right
                    if pp:
                        left, right = tables[1][pp - 1]
                if pp:
                    if not pulse_remaining:
                        if left >= 128:
                            pulse = ((left & 15) << 8) | right
                            pp += 1
                        else:
                            pulse_remaining = left
                    if pulse_remaining:
                        delta = right if right < 128 else right - 256
                        pulse = (pulse + delta) & 4095
                        pulse_remaining -= 1
                        if not pulse_remaining:
                            pp += 1
        frames.append({"frame": frame, "control": control, "control_hex": f"{control:02X}",
                       "relative_semitones": relative, "pulse": pulse})
    return frames


SELECTION = {
    "dojo.sng": {2: "Plucked/koto onset for samples13/15; compare complete note tails.",
                 7: "Faster pluck variation for samples13/15.",
                 10: "Sustained PWM lead candidate for sample14."},
    "transylvanian.sng": {1: "Harpsichord-like bright pluck candidate for13/15/16.",
                          2: "Pulse-to-triangle flute attack as a less buzzy lead alternative."},
    "consultant.sng": {3: "Pulse lead with explicit motion; candidate for14."},
    "funktest.sng": {10: "Saw lead seed for a brighter14 replacement."},
    "2xtest.sng": {4: "Lead used in an actual2x tune; rescale its table timing before a50Hz trial."},
}


def main() -> None:
    archive = SOURCE / "GoatTracker_2.77.zip"
    # Keep only research data and the documented format/player reference.
    with zipfile.ZipFile(archive) as package:
        for name in list("examples/" + name for name in SELECTION) + ["readme.txt", "copying", "src/player.s", "src/gsong.c", "src/gplay.c", "src/goattrk2.h"]:
            target = SOURCE / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(package.read(name))
    songs, seeds = [], []
    for filename, choices in SELECTION.items():
        song = read_song(SOURCE / "examples" / filename)
        songs.append({key: value for key, value in song.items() if key not in ("instruments", "tables")})
        for instrument_id, purpose in choices.items():
            instrument = dict(song["instruments"][instrument_id - 1])
            instrument["tables"] = {name: reachable_table(song["tables"][index], instrument["table_pointers"][index], index == 3)
                                    for index, name in enumerate(("wave", "pulse", "filter", "speed"))}
            instrument["adsr"] = {"attack": instrument["ad"] >> 4, "decay": instrument["ad"] & 15,
                                  "sustain": instrument["sr"] >> 4, "release": instrument["sr"] & 15}
            instrument["frame_program"] = frame_program(instrument, song["tables"])
            instrument["frame_rate_hz"] = 100 if filename == "2xtest.sng" else 50
            instrument["frame_program_limit"] = "32updates; standalone pulse initial0; no pattern effects or vibrato expansion. Raw speed table and vibrato delay retained. Source pulse-optimization timing can skip updates at row boundaries."
            instrument["filter_seed"] = {"mode": "off", "cutoff": None, "envelope": [],
                                          "note": "These selected instruments have no filter-table pointer. A standalone candidate explicitly disables filter; original songs may inherit a preceding global filter state."}
            seeds.append({"seed_id": f"{Path(filename).stem}-{instrument_id:02d}",
                          "song": song["title"], "author": song["author"], "song_file": song["file"],
                          "instrument": instrument, "proposed_use": purpose,
                          "verified": "Original GTS5 instrument metadata and reachable table rows decoded; full file layout consumed exactly.",
                          "not_verified": "No perceptual closeness ranking or waveform-equivalence claim. Tables have not yet been rendered over Stardust's phrase."})
    result = {"schema_version": 1, "official_author_page": "https://cadaver.github.io/tools.html",
              "official_distribution_url": ARCHIVE_URL,
              "downloaded_via": "https://sourceforge.net/projects/goattracker2/files/latest/download",
              "archive_name": archive.name,
              "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
              "format_reference": str((SOURCE / "readme.txt").resolve()),
              "license": "Distribution readme says GNU GPL; COPYING is retained. Player source has a separate unrestricted-use notice. No separate blanket public-domain statement for example music/instruments was found.",
              "songs": songs, "seeds": seeds,
              "table_semantics": {"clock": "One table step per tracker update; 2xtest is explicitly2x. Preserve or intentionally rescale timing.",
                                  "wave": "left10..DF=control; E0..EF maps to00..0F;01..0F=delay;FF=jump, right0=stop. Right00..5F relative semitones,60..7F negative,80 keeps frequency,81..DF absolute note.",
                                  "pulse": "left80..FE sets12bit width from low nibble+right;01..7F applies signed-right delta for left frames;FF jumps.",
                                  "filter": "Global chip resource: left90=LP,A0=BP,C0=HP; right contains resonance/routing. Rewrite routing for the chosen physical voice; avoid silently affecting other channels.",
                                  "restart": "first_wave and gate_timer are required context, not ordinary sustained waveform bytes. Common09 resets oscillator with TEST; gate timer schedules hard restart."}}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "sid-examples.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"songs": len(songs), "seeds": len(seeds), "output": str(OUTPUT / "sid-examples.json")}))
    for seed in seeds:
        ins = seed["instrument"]
        print(seed["seed_id"], ins["name"], f"AD={ins['ad']:02X} SR={ins['sr']:02X}",
              {name: [row["hex"] for row in rows] for name, rows in ins["tables"].items()})


if __name__ == "__main__":
    main()

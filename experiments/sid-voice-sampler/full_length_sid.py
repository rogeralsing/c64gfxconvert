"""Small native SID programs: reusable note descriptors, not register streams."""
from __future__ import annotations

from pathlib import Path
import json
import math

import native_support as support

HERE = Path(__file__).resolve().parent
CHORDS = {12: (0, 4, 7), 13: (0, 3, 7), 15: (0, 5, 9), 16: (0, 3, 8)}
DRUMS = {2, 3, 4, 5, 6, 9, 10}
DURATION = {2: 7, 3: 6, 4: 3, 5: 5, 6: 4, 9: 6, 10: 15}
SPECIAL = set(range(17, 23))


class Compiler:
    def __init__(self, roots: dict, programs: dict):
        self.roots, self.programs = roots, programs
        self.trios, self.trio_ids = [], {}
        self.words, self.word_ids = [0], {0: 0}

    def descriptor(self, identifier: int, state: dict | None, *, active=True,
                   accepted_level: int | None = None) -> list[int]:
        continuous_envelope = int(accepted_level is not None)
        if not identifier or state is None or not state["period"]:
            return [0, continuous_envelope, 0, 0, 0,
                    accepted_level if accepted_level is not None else 0]
        rate = support.PAULA / state["period"]
        word, index = 0, 0
        if identifier in CHORDS:
            fundamental = rate / self.roots[identifier]
            trio = tuple(round(fundamental * 2 ** (s / 12) * 2**24 / support.CLOCK)
                         for s in CHORDS[identifier])
            if trio not in self.trio_ids:
                if len(self.trios) % 256 > 253:
                    self.trios.extend([0] * (256 - len(self.trios) % 256))
                if len(self.trios) + 3 > 512:
                    raise ValueError("Chord frequency trios exceed the native512-entry table")
                self.trio_ids[trio] = len(self.trios)
                self.trios.extend(trio)
            index = self.trio_ids[trio]
        else:
            if identifier == 2:
                frequency = 55 * 254 / state["period"]
            elif identifier in (5, 6):
                frequency = 760 * 214 / state["period"]
            elif identifier in DRUMS:
                frequency = rate / (16 if identifier == 10 else 4)
            else:
                frequency = rate / self.roots[identifier]
            word = min(65535, max(1, round(frequency * 2**24 / support.CLOCK)))
        peak = self.programs[identifier]["peakSustain"]
        level = min(4, max(0, round(peak * state["volume"] / 64)))
        if state["volume"] < 8:
            level = 0
        if accepted_level is not None:
            level = accepted_level
        active = bool(active and (level or accepted_level is not None))
        if word not in self.word_ids:
            if len(self.words) >= 256:
                raise ValueError("Shared exact SID base-frequency dictionary exceeds256words")
            self.word_ids[word] = len(self.words)
            self.words.append(word)
        return [self.word_ids[word], continuous_envelope, identifier | (128 if active else 0), index & 255, index >> 8, level]

    def _voice(self, row: list[int], offset: int, age: int, arp: int) -> list[int]:
        identifier = row[offset + 2] & 127
        preset = self.programs.get(identifier, {"basePulse": 2048, "baseControl": 25})
        pulse, control = preset["basePulse"], preset["baseControl"]
        level, word = row[offset + 5], self.words[row[offset]]
        active = bool(row[offset + 2] & 128)
        if identifier in CHORDS:
            word = self.trios[(row[offset + 4] << 8) + row[offset + 3] + arp]
            pulse = 1966
        if identifier in DURATION and age >= DURATION[identifier]:
            active = False
        if not active or not control:
            return [0, 0, 25, pulse & 255, pulse >> 8,
                    level if row[offset + 1] & 1 else 0]
        if identifier == 2:
            word = min(65535, word << (2 if age == 0 else 1 if age == 1 else 0))
        elif identifier in (5, 6) and age == 0:
            word = min(65535, word << 1)
        elif identifier == 14:
            control, pulse = (65 if age < 2 else 33), 700
        elif identifier == 23:
            control = 33 if age < 2 else 65
            pulse = (1100, 1500, 1966, 2200)[(age >> 2) & 3]
        elif identifier == 24:
            control = 33
        elif identifier in SPECIAL:
            control = 129 if age == 0 else 33
            level = max(0, level - (2 if age >= 12 else 1 if age >= 6 else 0))
        return [word & 255, word >> 8, control, pulse & 255, pulse >> 8, level]

    def physical(self, rows: list[list[int]], *, fix_retriggers: bool = False) -> list[list[int]]:
        ages, arps = [0, 0], [0, 0]
        previous_levels, previous_active = [0, 0], [False, False]
        result = []
        for index, row in enumerate(rows):
            out = row.copy()
            for voice, offset in enumerate((0, 6)):
                if row[23] & (1 << voice):
                    ages[voice] = arps[voice] = 0
                else:
                    ages[voice] = min(255, ages[voice] + 1)
                    arps[voice] = (arps[voice] + 1) % 3
                physical = self._voice(row, offset, ages[voice], arps[voice])
                active = bool(row[offset + 2] & 128)
                rising = physical[5] > previous_levels[voice] or (active and not previous_active[voice])
                if fix_retriggers and rising and not (voice == 0 and index < 1000):
                    row[23] |= 1 << voice
                    ages[voice] = arps[voice] = 0
                    physical = self._voice(row, offset, 0, 0)
                out[offset:offset + 6] = physical
                previous_levels[voice], previous_active[voice] = physical[5], active
            out[23] = row[23]
            result.append(out)
        return result

    def emit(self, out: Path) -> Path:
        out.mkdir(parents=True, exist_ok=True)
        path = out / "sid-programs.asm"
        controls = [25] + [self.programs[i]["baseControl"] for i in range(1, 25)]
        pulses = [2048] + [self.programs[i]["basePulse"] for i in range(1, 25)]
        for i in CHORDS:
            pulses[i] = 1966
        controls[24] = 33
        lines = ['.pc = $f800 "Native reusable SID programs"',
                 f'.import source "{(HERE / "full-length-sid.asm").resolve()}"']
        tables = {"sid_controls": controls,
                  "sid_pulse_low": [p & 255 for p in pulses],
                  "sid_pulse_high": [p >> 8 for p in pulses],
                  "sid_durations": [DURATION.get(i, 0) for i in range(25)],
                  "sid_chords": [int(i in CHORDS) for i in range(25)],
                  "sid_frequency_low": [w & 255 for w in self.words],
                  "sid_frequency_high": [w >> 8 for w in self.words],
                  "sid_trio_low": [w & 255 for w in self.trios],
                  "sid_trio_high": [w >> 8 for w in self.trios]}
        for name, values in tables.items():
            lines += [name + ":", ".byte " + ",".join(map(str, values)) if values else ".byte 0"]
        lines += ["sid_program_end:", '.assert "Native SID programs must fit F800..FEFF", * <= $ff00, true']
        path.write_text("\n".join(lines) + "\n")
        support.save(out / "sid-programs.json", {"chord_trios": len(self.trios) // 3,
                      "trio_table_bytes": len(self.trios) * 2,
                      "base_frequency_words": len(self.words),
                      "base_frequency_table_bytes": len(self.words) * 2,
                      "score_fields": ["baseFrequencyID", "continuousEnvelope", "instrumentID|active128",
                                       "chordTrioBaseIndex", "chordTablePage0/1", "sustainLevel0..4"],
                      "native_state": "062c..063f; voice_record0620..062b; scratchZP60..6f"})
        return path

"""Compile sample-based four-channel MOD effects into a complete tick timeline.

The replay subset covers the converter's sample-based ProTracker corpus;
unsupported extended commands still fail explicitly. The period table and
per-tick effect order follow the ProTracker 2.3D clone's replay source:
https://github.com/8bitbubsy/pt2-clone/blob/master/src/pt2_replayer.c
"""
from __future__ import annotations

from protracker_periods import PERIODS, PERIOD_TABLE

VIBRATO = (0, 24, 49, 74, 97, 120, 141, 161, 180, 197, 212, 224, 235,
           244, 250, 253, 255, 253, 250, 244, 235, 224, 212, 197, 180,
           161, 141, 120, 97, 74, 49, 24)
SUPPORTED = {0x0, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9,
             0xA, 0xB, 0xC, 0xD, 0xE, 0xF}
EXTENDED = {0x1, 0x2, 0x5, 0x6, 0x9, 0xA, 0xB, 0xC, 0xD, 0xE}


def _quantize_period(period: int, finetune: int = 0) -> int:
    note = next((i for i, p in enumerate(PERIODS) if period >= p), 35)
    return PERIOD_TABLE[(finetune & 15) * 37 + note]


def _porta_target(period: int, finetune: int) -> int:
    base = (finetune & 15) * 37
    note = next((i for i in range(37) if period >= PERIOD_TABLE[base + i]), 35)
    if finetune < 0 and note > 0:
        note -= 1
    return PERIOD_TABLE[base + note]


def _volume_slide(channel: dict, param: int) -> None:
    delta = (param >> 4) if param & 0xF0 else -(param & 15)
    channel["volume"] = min(64, max(0, channel["volume"] + delta))


def _porta(channel: dict) -> None:
    target, current, step = channel["target"], channel["period"], channel["porta_speed"]
    if not target:
        return
    channel["period"] = min(target, current + step) if current < target else max(target, current - step)
    if channel["period"] == target:
        channel["target"] = 0


def _vibrato(channel: dict, param: int | None = None) -> int:
    if param is not None:
        if param & 15:
            channel["vib_depth"] = param & 15
        if param >> 4:
            channel["vib_speed"] = param >> 4
    phase = channel["vib_phase"]
    delta = (VIBRATO[(phase >> 2) & 31] * channel["vib_depth"]) >> 7
    result = channel["period"] + (delta if phase < 128 else -delta)
    channel["vib_phase"] = (phase + channel["vib_speed"] * 4) & 255
    return result


def _tremolo(channel: dict, param: int) -> int:
    if param & 15:
        channel["trem_depth"] = param & 15
    if param >> 4:
        channel["trem_speed"] = param >> 4
    phase = channel["trem_phase"]
    delta = (VIBRATO[(phase >> 2) & 31] * channel["trem_depth"]) >> 6
    result = min(64, channel["volume"] + delta) if phase < 128 else max(0, channel["volume"] - delta)
    channel["trem_phase"] = (phase + channel["trem_speed"] * 4) & 255
    return result


def _offset(channel: dict, param: int) -> None:
    if param:
        channel["offset_memory"] = param
    offset = channel["offset_memory"] * 256
    if offset < channel["remaining_bytes"]:
        channel["start_offset"] += offset
        channel["remaining_bytes"] -= offset
    else:
        # PT keeps its current start pointer and reduces the DMA length to
        # one word when an offset exceeds the remaining sample length.
        channel["remaining_bytes"] = 2
        channel["short_dma"] = True


def build_timeline(mod: dict) -> dict:
    """Return every executed tick, stopping before the next song repetition.

    ``channels[].period`` is the audible Amiga period after effects; it is not
    the frequency of a tonal sample's fundamental. Convert playback rate as
    3546894.6 / period. ``sample`` is selected instrument, ``playing_sample``
    is the most recently triggered sample. The latter distinction matters for
    instrument-only and portamento rows. A trigger starts at ``offset`` bytes.
    ``duration_s`` uses the effective BPM; an Fxx tempo change takes effect on
    the following tick, as in the CIA-driven ProTracker replay routine.
    """
    startrekker = mod.get("format") == "Startrekker FLT4"
    vblank = startrekker or mod.get("timing_mode") == "vblank"
    for pattern in mod["patterns"]:
        for row in pattern:
            for note in row:
                # E01 disables the Amiga LED filter, which is already absent
                # from this PCM renderer. Other E commands remain unsupported
                # unless their sample/sequence semantics are implemented below.
                if note["effect"] not in SUPPORTED:
                    raise ValueError(f"Unsupported ProTracker effect {note['effect']:X}{note['param']:02X}")
                if note["effect"] == 0xE and note["param"] != 0x01 and note["param"] >> 4 not in EXTENDED:
                    raise ValueError(f"Unsupported ProTracker effect E{note['param']:02X}")
                if startrekker and note["effect"] == 0xE and note["param"] != 0x01:
                    raise ValueError("Startrekker assembly macros are unsupported")
    states = [dict(sample=0, playing_sample=0, period=0, render_period=0, volume=0, target=0,
                   porta_speed=0, vib_depth=0, vib_speed=0, vib_phase=0, finetune=0,
                   trem_depth=0, trem_speed=0, trem_phase=0, offset_memory=0,
                   start_offset=0, remaining_bytes=0, loop_row=0, loop_count=0) for _ in range(4)]
    order = row = 0
    speed, bpm = 6, 125
    pending_bpm = None
    time_s = 0.0
    ticks, rows, seen, effects = [], [], set(), set()
    termination = "end_of_order_list"
    short_dma_triggers = 0
    while order < len(mod["orders"]):
        if pending_bpm is not None:
            bpm, pending_bpm = pending_bpm, None
        position = (order, row)
        if position in seen:
            termination = "repeated_position"
            break
        seen.add(position)
        notes = mod["patterns"][mod["orders"][order]][row]
        next_order, next_row = order, row + 1
        if next_row == 64:
            next_order, next_row = order + 1, 0
        triggers = [False] * 4
        trigger_offsets = [0] * 4
        trigger_lengths = [None] * 4
        stop = False
        delay = 0
        loop_target = None
        flow_jump = False
        for index, (state, note) in enumerate(zip(states, notes)):
            instrument, period = note["sample"], note["period"]
            effect, param = note["effect"], note["param"]
            if effect or param:
                effects.add(f"{effect:X}")
            if instrument:
                sample = mod["samples"][instrument - 1]
                state["sample"] = instrument
                state["volume"] = sample["volume"]
                state["finetune"] = sample["finetune"]
                state["start_offset"] = 0
                state["short_dma"] = False
                state["remaining_bytes"] = (sample["loop_start"] + sample["loop_length"]
                                            if sample["loop_start"] and sample["loop_length"] > 2
                                            else sample["length"])
            if effect == 0xE and param >> 4 == 5:
                state["finetune"] = (param & 15) - (16 if param & 8 else 0)
            if period:
                if effect in (3, 5):
                    target = _porta_target(period, state["finetune"])
                    state["target"] = target if target != state["period"] else 0
                else:
                    state["period"] = _quantize_period(period, state["finetune"])
                    if effect == 9:
                        _offset(state, param)
                    if effect != 0xE or param >> 4 != 0xD:
                        state["render_period"] = state["period"]
                        state["vib_phase"] = state["trem_phase"] = 0
                        state["playing_sample"] = state["sample"]
                        triggers[index] = True
                        trigger_offsets[index] = state["start_offset"]
                        if state.get("short_dma", False):
                            trigger_lengths[index] = 2
            if effect == 9:
                # With a new note PT calls sampleOffset before setPeriod and
                # again afterwards. The second adjustment affects a future
                # trigger; it must not move the just-started sample twice.
                _offset(state, param)
            if effect == 0xC:
                state["volume"] = min(param, 64)
            elif effect == 0xF:
                if param == 0:
                    stop = True
                elif param < 32 or vblank:
                    speed = min(param, 31) if startrekker else param
                else:
                    pending_bpm = param
            elif effect == 0xB:
                next_order, next_row = param, 0
                flow_jump = True
            elif effect == 0xD:
                next_order = order + 1
                flow_jump = True
                next_row = (param >> 4) * 10 + (param & 15)
                if next_row > 63:
                    next_row = 0
            elif effect == 0xE:
                command, value = param >> 4, param & 15
                if command == 0xE:
                    delay = value
            # C/B/D/F return before the tick-zero period write in PT. A new
            # triggered note already wrote its period above. Otherwise retain
            # the previous actual register value until the next write.
            # E01 likewise returns without writing a period, on every tick.
            if effect not in (0x9, 0xB, 0xC, 0xD, 0xE, 0xF):
                state["render_period"] = state["period"]
        rows.append({"order": order, "pattern": mod["orders"][order], "row": row,
                     "time_s": time_s, "speed": speed, "bpm": bpm})
        # The original fixed-BPM modules retain their ideal 50 Hz ticks.
        # Physical PAL CIA quantization is documented in the independent-
        # reference receipt rather than hidden in the score. New Fxx changes
        # preserve the old timer for tick zero, then use 2.5/BPM per tick.
        for repeated in range(delay + 1):
            for tick in range(speed):
                if (repeated or tick) and pending_bpm is not None:
                    bpm, pending_bpm = pending_bpm, None
                duration = 2.5 / bpm
                output = []
                for index, (state, note) in enumerate(zip(states, notes)):
                    effect, param = note["effect"], note["param"]
                    audible_period = state["render_period"]
                    volume = state["volume"]
                    trigger = bool(not repeated and tick == 0 and triggers[index])
                    offset = trigger_offsets[index] if trigger else 0
                    first_segment_bytes = trigger_lengths[index] if trigger else None
                    if tick > 0 or repeated:
                        if effect == 1:
                            state["period"] = max(113, state["period"] - param)
                        elif effect == 2:
                            state["period"] = min(856, state["period"] + param)
                        elif effect == 3:
                            if param:
                                state["porta_speed"] = param
                            _porta(state)
                        elif effect == 5:
                            _porta(state)
                            _volume_slide(state, param)
                        elif effect == 0xA:
                            _volume_slide(state, param)
                        if (effect or param) and effect != 0xE:
                            audible_period = state["period"]
                        if effect == 4:
                            audible_period = _vibrato(state, param)
                        elif effect == 6:
                            audible_period = _vibrato(state)
                            _volume_slide(state, param)
                        elif effect == 0 and param and state["period"]:
                            if tick % 3 == 0:
                                audible_period = state["period"]
                            else:
                                semitones = (param >> 4) if tick % 3 == 1 else (param & 15)
                                table_start = (state["finetune"] & 15) * 37
                                base = next((j for j in range(37) if state["period"] >= PERIOD_TABLE[table_start+j]), 35)
                                audible_period = PERIOD_TABLE[table_start + base + semitones]
                    if effect == 7 and (tick > 0 or repeated):
                        volume = _tremolo(state, param)
                    else:
                        volume = state["volume"]
                    if effect == 0xE:
                        command, value = param >> 4, param & 15
                        if command in (1, 2) and tick == 0:
                            state["period"] = max(113, state["period"] - value) if command == 1 else min(856, state["period"] + value)
                            audible_period = state["period"]
                        elif command == 6 and tick == 0:
                            if value == 0:
                                state["loop_row"] = row
                            else:
                                if state["loop_count"] == 0:
                                    state["loop_count"] = value
                                else:
                                    state["loop_count"] -= 1
                                if state["loop_count"]:
                                    loop_target = state["loop_row"]
                        elif command in (0xA, 0xB) and tick == 0:
                            state["volume"] = min(64, state["volume"] + value) if command == 0xA else max(0, state["volume"] - value)
                            volume = state["volume"]
                        elif command == 0xC and tick == value:
                            state["volume"] = volume = 0
                        elif command == 0x9 and value and tick % value == 0 and not (tick == 0 and note["period"]):
                            trigger = True
                        elif command == 0xD and tick == value and note["period"]:
                            trigger = True
                        if trigger:
                            state["playing_sample"] = state["sample"]
                            offset = state["start_offset"]
                            audible_period = state["period"]
                            first_segment_bytes = 2 if state.get("short_dma", False) else None
                    state["render_period"] = audible_period
                    if first_segment_bytes is not None:
                        short_dma_triggers += 1
                    output.append({"sample": state["sample"], "playing_sample": state["playing_sample"],
                                   "period": audible_period, "volume": volume,
                                   "trigger": trigger, "offset": offset})
                    if first_segment_bytes is not None:
                        output[-1]["first_segment_bytes"] = first_segment_bytes
                    if state["sample"] and state["sample"] != state["playing_sample"]:
                        # An instrument-only/portamento row updates Paula's
                        # next loop pointer, without replacing the currently
                        # playing sample segment. Keep these states separate.
                        output[-1]["loop_sample"] = state["sample"]
                ticks.append({"time_s": time_s, "duration_s": duration, "order": order,
                              "pattern": mod["orders"][order], "row": row, "tick": tick,
                              "speed": speed, "bpm": bpm, "channels": output})
                time_s += duration
                if stop:
                    break
            if stop:
                break
        if stop:
            termination = "F00"
            break
        if loop_target is not None:
            next_order, next_row = order, loop_target + bool(delay)
            # A finite E6 loop revisits rows intentionally. Clear only those
            # visit marks, as PT's MOD-to-WAV end detector does; a later Bxx
            # song repetition still terminates the first complete traversal.
            seen.difference_update((order, r) for r in range(loop_target, row + 1))
        elif flow_jump and delay:
            # PT takes Bxx/Dxx immediately on the row's tick zero, before
            # delayed repeat cycles finish. Those cycles then leave the
            # target row counter incremented, so the first target row is
            # skipped (the EE2+D31 combination in State of the Art does it).
            next_row += 1
            if next_row >= 64:
                next_order, next_row = next_order + 1, 0
        order, row = next_order, next_row
        if len(ticks) > 1000000:
            raise ValueError("Timeline exceeds safety limit")
    result = {"ticks": ticks, "rows": rows, "duration_s": time_s,
              "termination": termination, "next_order": order, "next_row": row,
              "effects_handled": sorted(effects), "finetunes": sorted({s["finetune"] for s in mod["samples"] if s["length"]}),
              "timing": "Ideal CIA 2.5/BPM tick duration; 50 Hz for this module" if all(t["bpm"] == 125 for t in ticks)
              else "Ideal CIA 2.5/BPM tick duration; ProTracker tempo writes take effect one tick later"}
    if short_dma_triggers:
        result["one_word_dma_triggers"] = short_dma_triggers
    if "8" in effects:
        # PT2's checkMoreEffects/chkefx2 has no effect-8 handler: 8xx is a
        # synchronization marker in this replay dialect, not stereo panning.
        result["effect_8_semantics"] = "ProTracker 2.3D no-op/synchronization marker; mono playback"
    if vblank:
        result["timing_mode"] = "vblank"
    return result

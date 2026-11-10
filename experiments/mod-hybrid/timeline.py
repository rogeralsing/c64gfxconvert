"""Compile Stardust Memories' ProTracker effects into a complete tick timeline.

This is intentionally a small, explicit replay subset. Unsupported effects and
nonzero instrument finetune fail rather than silently changing the song. The
selected module uses only finetune zero and the effects listed below.

Semantics checked against the ProTracker 2.3D clone's replay source:
https://github.com/8bitbubsy/pt2-clone/blob/master/src/pt2_replayer.c
"""
from __future__ import annotations

PERIODS = (856, 808, 762, 720, 678, 640, 604, 570, 538, 508, 480, 453,
           428, 404, 381, 360, 339, 320, 302, 285, 269, 254, 240, 226,
           214, 202, 190, 180, 170, 160, 151, 143, 135, 127, 120, 113)
VIBRATO = (0, 24, 49, 74, 97, 120, 141, 161, 180, 197, 212, 224, 235,
           244, 250, 253, 255, 253, 250, 244, 235, 224, 212, 197, 180,
           161, 141, 120, 97, 74, 49, 24)
SUPPORTED = {0x0, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0xA, 0xB, 0xC, 0xD, 0xF}


def _quantize_period(period: int) -> int:
    return next((p for p in PERIODS if period >= p), PERIODS[-1])


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


def build_timeline(mod: dict) -> dict:
    """Return every executed tick, stopping before the next song repetition.

    ``channels[].period`` is the audible Amiga period after effects; it is not
    the frequency of a tonal sample's fundamental. Convert playback rate as
    3546894.6 / period. ``sample`` is selected instrument, ``playing_sample``
    is the most recently triggered sample. The latter distinction matters for
    instrument-only and portamento rows. A trigger starts at ``offset`` bytes.
    """
    if any(s["finetune"] for s in mod["samples"] if s["length"]):
        raise ValueError("This experiment currently requires finetune-zero instruments")
    for pattern in mod["patterns"]:
        for row in pattern:
            for note in row:
                # E01 disables the Amiga LED filter, which is already absent
                # from this PCM renderer. Other E commands remain unsupported.
                filter_off = note["effect"] == 0xE and note["param"] == 0x01
                if note["effect"] not in SUPPORTED and not filter_off:
                    raise ValueError(f"Unsupported ProTracker effect {note['effect']:X}{note['param']:02X}")
    states = [dict(sample=0, playing_sample=0, period=0, render_period=0, volume=0, target=0,
                   porta_speed=0, vib_depth=0, vib_speed=0, vib_phase=0) for _ in range(4)]
    order = row = 0
    speed, bpm = 6, 125
    time_s = 0.0
    ticks, rows, seen, effects = [], [], set(), set()
    termination = "end_of_order_list"
    while order < len(mod["orders"]):
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
        stop = False
        for index, (state, note) in enumerate(zip(states, notes)):
            instrument, period = note["sample"], note["period"]
            effect, param = note["effect"], note["param"]
            if effect or param:
                effects.add(f"{effect:X}")
            if instrument:
                state["sample"] = instrument
                state["volume"] = mod["samples"][instrument - 1]["volume"]
            if period:
                period = _quantize_period(period)
                if effect in (3, 5):
                    state["target"] = period if period != state["period"] else 0
                else:
                    state["period"] = period
                    state["render_period"] = period
                    state["vib_phase"] = 0
                    state["playing_sample"] = state["sample"]
                    triggers[index] = True
            if effect == 0xC:
                state["volume"] = min(param, 64)
            elif effect == 0xF:
                if param == 0:
                    stop = True
                elif param < 32:
                    speed = param
                else:
                    raise ValueError("BPM changes need CIA one-tick delay handling; absent in selected module")
            elif effect == 0xB:
                next_order, next_row = param, 0
            elif effect == 0xD:
                next_order = order + 1
                next_row = (param >> 4) * 10 + (param & 15)
                if next_row > 63:
                    next_row = 0
            # C/B/D/F return before the tick-zero period write in PT. A new
            # triggered note already wrote its period above. Otherwise retain
            # the previous actual register value until the next write.
            # E01 likewise returns without writing a period, on every tick.
            if effect not in (0xB, 0xC, 0xD, 0xE, 0xF):
                state["render_period"] = state["period"]
        rows.append({"order": order, "pattern": mod["orders"][order], "row": row,
                     "time_s": time_s, "speed": speed, "bpm": bpm})
        # The song uses no BPM changes. Ideal 50 Hz ticks match libopenmpt's
        # default MOD timing. Physical PAL CIA quantization is documented in
        # the independent-reference receipt rather than hidden in the score.
        duration = 2.5 / bpm
        for tick in range(speed):
            output = []
            for index, (state, note) in enumerate(zip(states, notes)):
                effect, param = note["effect"], note["param"]
                audible_period = state["render_period"]
                if tick > 0:
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
                            base = next((j for j, p in enumerate(PERIODS) if state["period"] >= p), 35)
                            audible_period = PERIODS[min(35, base + semitones)]
                state["render_period"] = audible_period
                output.append({"sample": state["sample"], "playing_sample": state["playing_sample"],
                               "period": audible_period, "volume": state["volume"],
                               "trigger": bool(tick == 0 and triggers[index]), "offset": 0})
            ticks.append({"time_s": time_s, "duration_s": duration, "order": order,
                          "pattern": mod["orders"][order], "row": row, "tick": tick,
                          "speed": speed, "bpm": bpm, "channels": output})
            time_s += duration
            if stop:
                break
        if stop:
            termination = "F00"
            break
        order, row = next_order, next_row
        if len(ticks) > 1000000:
            raise ValueError("Timeline exceeds safety limit")
    return {"ticks": ticks, "rows": rows, "duration_s": time_s,
            "termination": termination, "next_order": order, "next_row": row,
            "effects_handled": sorted(effects), "finetunes": [0],
            "timing": "Ideal CIA 2.5/BPM tick duration; 50 Hz for this module"}

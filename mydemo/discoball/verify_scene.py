#!/usr/bin/env python3
"""Verify real PAL scene startup, SPACE/timer exits, detached pieces and silence."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess

import numpy as np
from PIL import Image

import verify as reference
import verify_music as music_reference
from model import coefficients, model, project


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PAL = 19656
FADE_IN, ZOOM_IN, RUN, EXPLODE, FADE_OUT, DONE = range(6)
VX = (-12, -4, 6, 14, 12, 2, -8, -14)
VY = (-10, -14, -12, -4, 8, 14, 12, 2)


def space_snapshot(source, target):
    """Press SPACE in VICE's keyboard matrix, without changing any C64 RAM.

    The official KEYBOARD 1.1 snapshot module stores DWORD row/reverse arrays:
    https://github.com/VICE-Team/svn-mirror/blob/master/vice/src/keyboard.c
    This exercises the CIA keyboard path even when the KERNAL is disabled.
    """
    original = source.read_bytes()
    data = bytearray(original)
    offset = data.find(b"KEYBOARD\0")
    assert offset >= 0, "VICE snapshot has no keyboard matrix module"
    assert data[offset+16:offset+18] == bytes((1, 1)), "Unsupported VICE keyboard snapshot version"
    length = struct.unpack_from("<I", data, offset+18)[0]
    assert length >= 22+96, "VICE keyboard matrix module is incomplete"
    payload = offset+22
    for location, mask in ((payload+7*4, 1 << 4), (payload+16*4+4*4, 1 << 7)):
        struct.pack_into("<I", data, location, struct.unpack_from("<I", data, location)[0] | mask)
    changes = [index for index, pair in enumerate(zip(original, data)) if pair[0] != pair[1]]
    assert changes and all(payload <= index < offset+length for index in changes)
    target.write_bytes(data)
    return {"method": "VICE KEYBOARD matrix snapshot", "row": 7, "column": 4,
            "changed_snapshot_bytes": changes, "c64_ram_changed": False}


def fade_maps():
    packed = np.frombuffer((HERE/"build/scene-fade.bin").read_bytes(), dtype=np.uint8).reshape(8, 256)
    colors = np.frombuffer((HERE/"build/scene-fade-sprites.bin").read_bytes(), dtype=np.uint8).reshape(8, 16)
    palette = [tuple(int(value, 16) for value in line.split()[:3])
               for line in (ROOT/"palettes/colodore.vpl").read_text().splitlines()
               if line.strip() and not line.startswith("#")]
    rgb = np.asarray(palette, dtype=np.int64)
    luminance = rgb @ np.asarray((2126, 7152, 722))
    assert np.all(colors[0] == 0) and np.array_equal(colors[7], np.arange(16))
    assert np.all(np.diff(luminance[colors], axis=0) >= 0), "Fade becomes brighter in the wrong direction"
    for source in range(16):
        # Independent minimum-cost path through the sixteen-color palette.
        costs = np.full(16, np.inf)
        costs[0] = 0
        for level in range(1, 8):
            error = ((7*rgb-level*rgb[source])**2).sum(axis=1)
            costs = np.asarray([error[target]+min(costs[luminance <= luminance[target]]) for target in range(16)])
        chosen_error = sum(int(((7*rgb[colors[level, source]]-level*rgb[source])**2).sum()) for level in range(1, 8))
        assert chosen_error == costs[source], "Fade path is not the closest monotonic palette approximation"
    for level in range(8):
        expected = np.asarray([int(colors[level, value >> 4]) << 4 | int(colors[level, value & 15]) for value in range(256)], dtype=np.uint8)
        assert np.array_equal(packed[level], expected), "Packed fade map changes the wrong nibble"
    return packed, colors, palette, luminance


class Scene:
    def __init__(self, executable, output):
        self.output = output
        output.mkdir(parents=True, exist_ok=True)
        self.labels = reference.common.read_labels(HERE/"build/hexagon/main.sym")
        self.program = HERE/"build/hexagon/sprite-ball.prg"
        self.hash = hashlib.sha256(self.program.read_bytes()).hexdigest()
        self.packed, self.color_maps, self.palette, self.luminance = fade_maps()
        self.sources = [(HERE/"build"/name).read_bytes() for name in ("ball-screen.bin", "ball-screen-b.bin", "ball-colors.bin")]
        self.faces = model("hexagon")
        self.log = (output/"vice.log").open("w")
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        command = reference.common.vice_command(executable, self.program, port, ROOT/"palettes/colodore.vpl")
        command += ["-initbreak", "reset", "-sound", "-sidmodel", "1", "-soundwarpmode", "1"]
        self.process = subprocess.Popen(command, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        self.connection = reference.common.connect_monitor(self.process, port)
        self.monitor = reference.common.Monitor(self.connection)
        self.connection.settimeout(180)
        self.monitor.run("r")
        self.monitor.run("sidefx off")
        self.snapshots = []

    def close(self):
        (self.output/"monitor.log").write_text("\n".join(self.monitor.transcript))
        try:
            self.connection.sendall(b"quit\n")
        except OSError:
            pass
        self.connection.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.log.close()

    def checkpoint(self, command):
        return reference.checkpoint(self.monitor, command)

    def at(self, name):
        number = self.checkpoint(f"break {self.labels[name]:04x}")
        self.monitor.run("x")
        assert self.monitor.registers()[0] == self.labels[name], f"Did not reach {name}"
        self.monitor.run(f"delete {number}")

    def sample(self):
        pc, raster, cycles = self.monitor.registers()
        self.monitor.run("bank ram")
        ram = self.monitor.memory(self.output/"ram.bin", 0, 65535)
        self.monitor.run("bank io")
        vic = self.monitor.memory(self.output/"vic.bin", 0xd000, 0xd03f)
        color = bytes(value & 15 for value in self.monitor.memory(self.output/"colors.bin", 0xd800, 0xdbe7))
        self.monitor.run("bank cpu")
        assert ram[0x9400:0x97e8] == self.sources[0]
        assert ram[0xd000:0xd3e8] == self.sources[1]
        assert ram[0x1000:0x13e8] == self.sources[2]
        assert ram[0xd400:0xdc00] == self.packed.tobytes(), "Fade lookup RAM was corrupted by an IRQ/SID write"
        assert ram[self.labels["missedDeadlines"]] == 0, "Scene missed a sprite presentation deadline"
        return {"pc": pc, "raster": raster, "cycles": cycles, "origin": cycles-raster*63,
                "ram": ram, "vic": vic, "color": color,
                "state": ram[self.labels["sceneState"]],
                "ticks": self.word(ram, "sceneTicks"), "level": ram[self.labels["fadeLevel"]]}

    def word(self, ram, name):
        address = self.labels[name]
        return int.from_bytes(ram[address:address+2], "little")

    def attributes(self, sample):
        ram = sample["ram"]
        return (ram[0x400:0x7e8], ram[0x7c00:0x7fe8], sample["color"])

    def check_fade(self, sample, initial=None):
        ram = sample["ram"]
        level, work = sample["level"], ram[self.labels["fadeWorkLevel"]]
        assert 0 <= level <= 7 and 0 <= work <= 7
        for channel, (live, source) in enumerate(zip(self.attributes(sample), self.sources)):
            values = np.frombuffer(live, dtype=np.uint8)
            original = np.frombuffer(source, dtype=np.uint8)
            completed, pending = self.packed[level, original], self.packed[work, original]
            valid = (values == completed) | (values == pending)
            if initial is not None:
                valid |= values == np.frombuffer(initial[channel], dtype=np.uint8)
            if channel == 2 and sample["state"] >= EXPLODE and level == 7:
                # The last RUN disco color can remain until that cell is faded.
                cells = json.loads((HERE/"build/scene.json").read_text())["disco"]["cells"]
                valid[cells] = True
            assert np.all(valid), "Live attributes do not follow the current monotonic fade passes"

    def black(self, sample):
        assert all(not any(values) for values in self.attributes(sample)), "Scene finished with nonblack attributes"
        assert sample["vic"][0x15] == 0, "Scene finished with enabled sprites"

    def capture(self, name):
        path = self.output/f"{name}.png"
        self.monitor.run(f'screenshot "{path}" 2')
        self.snapshots.append(str(path))

    def dump(self, name):
        path = self.output/f"{name}.vsf"
        self.monitor.run(f'dump "{path}"')
        return path

    def restore(self, path):
        self.monitor.run("delete")
        self.monitor.run(f'undump "{path}"')
        self.monitor.run("warp on")

    def intro(self):
        self.at("beginFadeIn")
        initial = self.sample()
        self.black(initial)
        self.capture("initial-black")
        self.monitor.run("warp on")
        irq = self.checkpoint(f"break {self.labels['nmiReturn']:04x}")
        pose = self.checkpoint(f"break {self.labels['framePresented']:04x}")
        running = self.checkpoint(f"break {self.labels['sceneRunning']:04x}")
        sid = self.checkpoint("trace store d400 d418")
        sid_events, irq_count, scales, levels = [], 0, [], set()
        partial = None
        last_level = 0
        while True:
            response = self.monitor.run("x")
            if irq_count < 16:
                sid_events.extend(music_reference.events(response))
            sample = self.sample()
            if sample["pc"] == self.labels["sceneRunning"]:
                assert sample["state"] == RUN
                assert all(live == source for live, source in zip(self.attributes(sample), self.sources))
                start = self.dump("run-start")
                self.monitor.run("delete")
                break
            self.check_fade(sample)
            if sample["state"] == FADE_IN:
                assert sample["vic"][0x15] == 0, "Ball appeared before the background fade completed"
                assert sample["level"] >= last_level
                last_level = sample["level"]
                levels.add(sample["level"])
                if partial is None and sample["level"] == 0 and any(self.attributes(sample)[0]):
                    partial = self.dump("partial-first-fade")
                if sample["level"] == 3 and not any("fade-middle" in path for path in self.snapshots):
                    self.capture("fade-middle")
            elif sample["state"] == ZOOM_IN:
                assert all(live == source for live, source in zip(self.attributes(sample), self.sources)), "Ball entry started before full background colors"
                if sample["pc"] == self.labels["framePresented"]:
                    scale = sample["ram"][self.labels["zoomScale"]]
                    assert scale == sample["ram"][self.labels["sceneZoomScale"]]
                    assert not scales or scale >= scales[-1], "Entry zoom shrank during its arrival"
                    scales.append(scale)
                    self.check_entry(sample, scale)
                    if scale >= 30 and not any("zoom-middle" in path for path in self.snapshots):
                        self.capture("zoom-middle")
            else:
                raise AssertionError("Intro skipped directly to an outro state")
            if sample["pc"] == self.labels["nmiReturn"]:
                irq_count += 1
                if irq_count == 16:
                    self.monitor.run(f"disable {sid}")
        stores = []
        for event in sid_events:
            if event["access"] != "store":
                continue
            instruction = event["instruction"]
            operation = re.search(r"\s(STA|STX|STY)\s", instruction)
            register = {"STA": "A", "STX": "X", "STY": "Y"}[operation[1]]
            value = int(re.search(rf"\b{register}:([0-9a-fA-F]{{2}})", instruction)[1], 16)
            stores.append((event["address"], value))
        digest = hashlib.sha256(json.dumps(stores, separators=(",", ":")).encode()).hexdigest()
        assert digest == music_reference.ORIGINAL_SID_TRACE_SHA256, "Music changed during banked background fading"
        assert partial and scales and min(scales) == 0 and max(scales) >= 63
        assert levels == set(range(7)), "Intro did not complete every background fade level"
        return start, partial, {"pal_ticks": irq_count, "entry_scales": scales, "fade_levels": sorted(levels | {7}),
                               "initial_sid_trace_sha256": digest}

    def check_entry(self, sample, scale):
        ram, vic = sample["ram"], sample["vic"]
        assert ram[self.labels["angleYaw"]] == ram[self.labels["anglePitch"]] == 0
        matrix = reference.zoom_matrix(coefficients(0, 0), scale)
        visible = [index for index, face in enumerate(self.faces) if project(face, matrix)[0] < 0]
        selected = sorted(sorted(visible, key=lambda index: (project(self.faces[index], matrix)[0], index))[:8])
        base = ram[self.labels["shownMetadataBase"]]
        assert list(ram[self.labels["slotFace"]+base:self.labels["slotFace"]+base+len(selected)]) == selected
        buffer = 0x0c00+(base//8)*512
        for slot, face in enumerate(selected):
            _, points = project(self.faces[face], matrix)
            low_x, low_y = min(x for x, y in points), min(y for x, y in points)
            expected = reference.polygon_bytes([(x-low_x, y-low_y) for x, y in points])
            assert ram[buffer+slot*64:buffer+slot*64+63] == expected, "Entry zoom sprite pixels differ from its intended scale"

    def exit_case(self, snapshot, name, space=False, timer=False):
        path = snapshot
        keyboard = None
        if space:
            path = self.output/f"{name}-space.vsf"
            keyboard = space_snapshot(snapshot, path)
        self.restore(path)
        cancellation = snapshot.name == "partial-first-fade.vsf"
        initial_attributes = self.attributes(self.sample()) if cancellation else None
        previous_attributes = None
        if space:
            key_read = self.checkpoint("watch load dc01")
            self.monitor.run("x")
            self.monitor.run("step")
            registers = self.monitor.run("r")
            accumulator = int(re.search(r"(?m)^\.;[0-9a-fA-F]{4}\s+([0-9a-fA-F]{2})", registers)[1], 16)
            assert accumulator&0x10 == 0, "SPACE did not pull the actual CIA keyboard input low"
            keyboard["cia_space_line_low"] = True
            self.monitor.run(f"delete {key_read}")
            if cancellation:
                initial_attributes = self.attributes(self.sample())
        if timer:
            start = self.sample()
            assert start["state"] == RUN and start["ticks"] == 0
            deadline = self.checkpoint(f"watch store {self.labels['missedDeadlines']:04x}")
            ending = self.checkpoint(f"break {self.labels['sceneBeginOutro']:04x}")
            tick = self.checkpoint(f"break {self.labels['nmiReturn']:04x}")
            completed = 0
            while completed < 9021:
                batch = min(500, 9021-completed)
                self.monitor.run(f"ignore {tick} ${batch-1:x}")
                try:
                    self.monitor.run("x")
                except RuntimeError as error:
                    try:
                        returncode = self.process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        returncode = None
                    (self.output/"timer-process-exit.json").write_text(json.dumps({"pid": self.process.pid, "returncode_before_cleanup": returncode, "error": str(error)}, indent=2)+"\n")
                    raise
                completed += batch
                before = self.sample()
                assert before["state"] == RUN and before["ticks"] == completed, "Timer exited before its required PAL ticks"
                assert abs(before["origin"]-start["origin"]-completed*PAL) < 64, "RUN counter differs from real completed PAL IRQs"
                print(f"Verified timer RUN tick {completed}/9022", flush=True)
            self.monitor.run("x")
            boundary = self.sample()
            assert boundary["ticks"] == 9022 and boundary["state"] == RUN
            assert abs(boundary["origin"]-start["origin"]-9022*PAL) < 64, "Timer did not count real PAL frames"
            self.monitor.run(f"delete {tick}")
            self.monitor.run("x")
            assert self.monitor.registers()[0] == self.labels["sceneBeginOutro"]
            self.monitor.run("delete")
        irq = self.checkpoint(f"break {self.labels['nmiReturn']:04x}")
        pose = self.checkpoint(f"break {self.labels['framePresented']:04x}")
        sid = self.checkpoint("trace store d418 d418")
        states, fragments, volumes = [], [], []
        baseline = None
        last_age = last_fragment_origin = None
        finished = 0
        for _ in range(1500):
            response = self.monitor.run("x")
            for event in music_reference.events(response):
                if event["access"] == "store":
                    volumes.append(int(re.search(r"\bA:([0-9a-fA-F]{2})", event["instruction"])[1], 16)&15)
            sample = self.sample()
            states.append(sample["state"])
            self.check_fade(sample, initial_attributes)
            if cancellation and sample["state"] >= FADE_OUT:
                current_attributes = self.attributes(sample)
                if previous_attributes is not None:
                    for before, after in zip(previous_attributes, current_attributes):
                        old, new = np.frombuffer(before, dtype=np.uint8), np.frombuffer(after, dtype=np.uint8)
                        assert np.all(self.luminance[new&15] <= self.luminance[old&15]) and np.all(self.luminance[new>>4] <= self.luminance[old>>4]), "Cancelled fade became brighter during its black restoration"
                previous_attributes = current_attributes
            if sample["state"] == EXPLODE and sample["pc"] == self.labels["framePresented"]:
                baseline, fragment = self.check_fragments(sample, baseline)
                if last_age is not None:
                    assert fragment["age"] == last_age+1
                    assert abs(sample["origin"]-last_fragment_origin-2*PAL) < 64, "Explosion skipped its two-PAL-frame presentation cadence"
                last_age = fragment["age"]
                last_fragment_origin = sample["origin"]
                fragments.append(fragment)
                if fragment["age"] in (0, 8, 20):
                    self.capture(f"{name}-explosion-{fragment['age']:02d}")
            if sample["state"] == DONE:
                self.black(sample)
                finished += 1
                if finished == 1:
                    self.capture(f"{name}-done-black")
                if finished == 3:
                    break
        else:
            raise AssertionError("Scene outro did not finish")
        assert volumes and volumes[-1] == 0, "SID volume did not finish muted"
        if fragments:
            assert fragments[0]["age"] == 0 and fragments[-1]["age"] == 44 and len(fragments) == 45
            assert len(set(zip(VX[:baseline["count"]], VY[:baseline["count"]]))) == baseline["count"]
        elif snapshot.name != "partial-first-fade.vsf":
            raise AssertionError("Visible ball exited without detached fragments")
        self.monitor.run("delete")
        return {"keyboard_input": keyboard, "timer_pal_ticks": 9022 if timer else None,
                "states_observed": sorted(set(states)), "fragment_presentations": len(fragments),
                "fragments": fragments, "final_sid_volume": volumes[-1], "final_black": True,
                "missed_deadlines": 0, "fragment_pal_ticks_per_presentation": 2}

    def check_fragments(self, sample, baseline):
        ram, vic, labels = sample["ram"], sample["vic"], self.labels
        age, count = ram[labels["explosionAge"]], ram[labels["explosionCount"]]
        ids = tuple(ram[labels["explosionFaces"]:labels["explosionFaces"]+count])
        positions = []
        for slot in range(count):
            xy = []
            for axis in ("X", "Y"):
                value = ram[labels[f"explosion{axis}Lo"]+slot] | ram[labels[f"explosion{axis}Hi"]+slot]<<8
                xy.append(value if value < 32768 else value-65536)
            positions.append(tuple(xy))
        yaw, pitch, scale = (ram[labels[name]] for name in ("angleYaw", "anglePitch", "explosionScale"))
        if baseline is None:
            assert age == 0 and 1 <= count <= 8
            matrix = reference.zoom_matrix(coefficients(yaw, pitch), scale)
            depths = [project(face, matrix)[0] for face in self.faces]
            expected_ids = tuple(sorted(sorted((face for face in range(20) if depths[face] < 0), key=lambda face: (depths[face], face))[:8]))
            assert ids == expected_ids, "Explosion did not detach the original visible hexagons"
            center = json.loads((HERE/"build/scene.json").read_text())["center"]
            expected_origins = []
            for face in ids:
                _, points = project(self.faces[face], matrix)
                expected_origins.append(((center[0]-104+2*min(x for x, y in points))&255,
                                         (center[1]-78+2*min(y for x, y in points))&255))
            assert positions == expected_origins, "Detached fragments jumped away from their original face origins"
            baseline = {"count": count, "ids": ids, "positions": positions, "yaw": yaw, "pitch": pitch, "scale": scale}
        assert count == baseline["count"] and ids == baseline["ids"], "Explosion replaced detached face identities"
        assert (yaw, pitch, scale) == ((baseline["yaw"]+6*age)&255, (baseline["pitch"]+4*age)&255, baseline["scale"])
        assert positions == [(x+VX[slot]*age, y+VY[slot]*age) for slot, (x, y) in enumerate(baseline["positions"])], "Fragments orbit or share motion instead of travelling independently"
        matrix = reference.zoom_matrix(coefficients(yaw, pitch), scale)
        base = ram[labels["shownMetadataBase"]]
        buffer = 0x0c00+(base//8)*512
        mirror = 0x7800+(base//8)*512
        assert ram[buffer:buffer+512] == ram[mirror:mirror+512], "Detached geometry differs between MCI fields"
        assert tuple(ram[labels["slotFace"]+base:labels["slotFace"]+base+count]) == ids
        enabled = 0
        for slot, (face, (x, y)) in enumerate(zip(ids, positions)):
            visible = x+48 > 24 and x <= 343 and y+42 > 50 and y <= 249
            actual = ram[buffer+slot*64:buffer+slot*64+63]
            if not visible:
                assert actual == bytes(63), "Hidden fragment left wrapped sprite pixels"
                continue
            enabled |= 1 << slot
            encoded_x = vic[2*slot] | ((vic[0x10] >> slot)&1)<<8
            decoded_x = encoded_x-504 if 481 <= encoded_x <= 503 else encoded_x
            assert (decoded_x, vic[2*slot+1]) == (x, y), "Fragment position wrapped at the display edge"
            depth, points = project(self.faces[face], matrix)
            low_x, low_y = min(px for px, py in points), min(py for px, py in points)
            assert actual == reference.polygon_bytes([(px-low_x, py-low_y) for px, py in points])
            source = reference.expected_front_color(-abs(depth) if depth else -1)
            assert vic[0x27+slot]&15 == self.color_maps[sample["level"], source], "Fragment lighting did not follow the global fade"
        assert vic[0x15] == enabled, "Clipped fragments reappeared at the opposite edge"
        return baseline, {"age": age, "face_ids": ids, "positions": positions, "visible_mask": enabled}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vice", default=shutil.which("x64sc"))
    args = parser.parse_args()
    scene = Scene(args.vice, HERE/"build/hexagon/scene-verification")
    try:
        run_start, partial, intro = scene.intro()
        report = {"prg_sha256": scene.hash, "intro": intro,
                  "early_space": scene.exit_case(partial, "early-space", space=True),
                  "run_space": scene.exit_case(run_start, "run-space", space=True),
                  "timer": scene.exit_case(run_start, "timer", timer=True),
                  "captures": scene.snapshots}
        (scene.output/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        print(json.dumps({key: value for key, value in report.items() if key != "captures"}, indent=2))
    finally:
        scene.close()


if __name__ == "__main__":
    main()

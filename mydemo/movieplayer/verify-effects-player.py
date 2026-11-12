#!/usr/bin/env python3
"""Verify animated ECM effects at the actual PAL VIC-II output boundary.

The oracle reads the approved screen/color movies, not compressed player data.
Credible failures include stale Color RAM, incorrect mirror color exchange,
history indexing, crop movement during a flash, and a color copy overtaken by
the beam. The static ECM verifier cannot observe those animation contracts.
Only ordinary monitor breakpoints and optional base-clock shortening are used;
the player has no test-only execution path.
"""

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import socket
import statistics
import subprocess

import numpy as np
from PIL import Image, ImageChops, ImageDraw


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BACKGROUNDS = (0, 12, 15, 1)
FONT_SHA = "180223a47f20c13a5ca203d00d80cc49db6d3d5504589c02c0ed59d01870043f"
PAL_CLOCK = 985248
PAL_FRAME_CYCLES = 19656


def sha(value):
    return hashlib.sha256(value).hexdigest()


def pose(serial):
    return 0 if serial <= 0 else 1 + (serial - 1) % 48


def labels_from(path):
    return {name: int(address, 16) for name, address in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}


def load_monitor_api():
    spec = importlib.util.spec_from_file_location("ecm_effects_monitor", HERE / "vice_monitor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Oracle:
    def __init__(self, data, object_names):
        self.data = data
        self.font = (data / "font.bin").read_bytes()
        assert len(self.font) == 512 and sha(self.font) == FONT_SHA
        palette = json.loads((data / "palette.json").read_text())
        self.levels = np.array([palette["c64Colors"][str(index)][0] for index in BACKGROUNDS], dtype=np.uint8)
        assert self.levels.tolist() == [0, 120, 174, 255]
        self.c64_levels = np.zeros(16, dtype=np.uint8)
        self.c64_levels[list(BACKGROUNDS)] = self.levels
        self.glyphs = np.unpackbits(np.frombuffer(self.font, dtype=np.uint8)).reshape(64, 8, 8)
        self.names = object_names
        self.screens, self.colors, self.frames = [], [], []
        for name in object_names:
            screens = np.frombuffer((data / name / "screen.frames").read_bytes(), dtype=np.uint8).reshape(49, 1000)
            colors = np.frombuffer((data / name / "color.frames").read_bytes(), dtype=np.uint8).reshape(49, 1000)
            self.screens.append(screens)
            self.colors.append(colors)
            self.frames.append(np.array([self.decode(s, c) for s, c in zip(screens, colors)]))

    def decode(self, screen, colors):
        masks = self.glyphs[np.asarray(screen) & 63]
        backgrounds = self.levels[np.asarray(screen) >> 6]
        foregrounds = self.c64_levels[np.asarray(colors) & 15]
        return np.where(masks, foregrounds[:, None, None], backgrounds[:, None, None]).reshape(25, 40, 8, 8).transpose(0, 2, 1, 3).reshape(200, 320)

    def validate_zoom(self, mapping, swapping):
        mapping = np.asarray(mapping, dtype=np.uint8).reshape(64, 4)
        swapping = np.asarray(swapping, dtype=np.uint8).reshape(64, 4)
        assert np.all(mapping < 64) and np.all(swapping < 2)
        errors = []
        candidates = np.concatenate((self.glyphs, 1 - self.glyphs))
        for code, glyph in enumerate(self.glyphs):
            enlarged = glyph.repeat(2, axis=0).repeat(2, axis=1)
            for quadrant in range(4):
                y, x = (quadrant >> 1) * 8, (quadrant & 1) * 8
                target = enlarged[y:y + 8, x:x + 8]
                possible = np.count_nonzero(candidates != target, axis=(1, 2))
                chosen = int(mapping[code, quadrant]) + 64 * int(swapping[code, quadrant])
                assert possible[chosen] == possible.min(), ("Suboptimal zoom glyph", code, quadrant)
                errors.append(int(possible[chosen]))
        self.zoom_mapping, self.zoom_swapping = mapping, swapping
        return {"quarters": len(errors), "maxWrongPixels": max(errors), "meanWrongPixels": statistics.mean(errors), "exactQuarters": errors.count(0)}

    def zoom(self, object_id, frame, crop):
        output = np.zeros((200, 320), dtype=np.uint8)
        cx, cy = crop
        for y in range(12):
            for x in range(20):
                at = (y + cy) * 40 + x + cx
                screen, fg = self.screens[object_id][frame, at], self.colors[object_id][frame, at]
                code, bg = int(screen & 63), int(self.levels[screen >> 6])
                foreground = int(self.c64_levels[fg & 15])
                for quadrant in range(4):
                    glyph = self.glyphs[self.zoom_mapping[code, quadrant]]
                    if self.zoom_swapping[code, quadrant]:
                        glyph = 1 - glyph
                    yy, xx = (y * 2 + (quadrant >> 1)) * 8, (x * 2 + (quadrant & 1)) * 8
                    output[yy:yy + 8, xx:xx + 8] = np.where(glyph, foreground, bg)
        return output

    def image(self, object_id, serial, mode, crop=(10, 6)):
        frame = pose(serial)
        source = self.frames[object_id][frame]
        output = np.zeros((200, 320), dtype=np.uint8)
        if mode == 0:
            output[:] = source
        elif mode in (1, 2, 7):
            for row in range(25):
                age = math.floor(4.5 + 4.5 * math.sin(2 * math.pi * (row / 24 + (serial % 48) / 48)) + .5) if mode == 1 else 0
                for column in range(40):
                    parity = ((row // 4) ^ (column // 4)) & 1
                    obj = parity if mode == 7 else object_id
                    selected = frame if mode == 7 else pose(serial - 24) if mode == 2 and parity else pose(serial - age)
                    output[row * 8:row * 8 + 8, column * 8:column * 8 + 8] = self.frames[obj][selected, row * 8:row * 8 + 8, column * 8:column * 8 + 8]
        elif mode == 3:
            output[:96] = source[:96]
            output[96:192] = source[:96][::-1]
        elif mode == 4:
            output[:, :160] = source[:, :160]
            output[:, 160:] = source[:, :160][:, ::-1]
        elif mode == 5:
            corner = source[:96, :160]
            output[:96, :160] = corner
            output[:96, 160:] = corner[:, ::-1]
            output[96:192, :160] = corner[::-1]
            output[96:192, 160:] = corner[::-1, ::-1]
        elif mode == 6:
            output = self.zoom(object_id, frame, crop)
        elif mode == 8:
            star, cube = self.frames[0][frame, :96, :160], self.frames[1][frame, :96, :160]
            output[:96, :160] = star
            output[:96, 160:] = cube[:, ::-1]
            output[96:192, :160] = cube[::-1]
            output[96:192, 160:] = star[::-1, ::-1]
        else:
            raise AssertionError(("Unknown effect", mode))
        if mode in (3, 5, 6, 8):
            shifted = np.zeros_like(output)
            shifted[4:196] = output[:192]
            output = shifted
        return Image.fromarray(output, "L").convert("RGB")


def compare_scanout(path, expected):
    actual = Image.open(path).convert("RGB").crop((32, 35, 352, 235))
    difference = ImageChops.difference(actual, expected)
    if difference.getbbox():
        difference.save(path.with_name(path.stem + "-difference.png"))
        expected.save(path.with_name(path.stem + "-expected.png"))
        raise AssertionError("Actual completed VIC field differs: " + path.name)
    return {"comparedPixels": 64000, "differentPixels": 0}


def script(step):
    if step < 36:
        return step // 12, 6 if step & 1 else (step % 12) // 2
    return 0, {36: 7, 37: 6, 38: 8, 39: 6}[step]


def duration(step):
    return 25 if step & 1 else 501


def image_from_ram(oracle, ram, first, colors, mode):
    pixels = oracle.decode(np.frombuffer(ram[first:first + 1000], dtype=np.uint8), np.frombuffer(colors, dtype=np.uint8))
    if mode in (3, 5, 6, 8):
        shifted = np.zeros_like(pixels)
        shifted[4:196] = pixels[:192]
        pixels = shifted
    return Image.fromarray(pixels, "L").convert("RGB")


def verify_unused_foreground_boundary(build, data, output, vice, crop_stress=False):
    """A legal invisible FG outside the movie palette must survive or reactivate.

    All prior screen glyphs are blank, so foreground2 is invisible. The next
    ordinary ball frame has more than256 visible glyphs and must repair their
    foregrounds, take the sequential fallback, and show one exact first field.
    This setup changes monitor inputs only; no production path is injected.
    """
    build, data, output = build.resolve(), data.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    labels = labels_from(build / "main.sym")
    oracle = Oracle(data, ["star-lit", "cube-lit", "ball-lit"])
    oracle.validate_zoom(np.frombuffer((build / "zoom-map.bin").read_bytes(), dtype=np.uint8),
                         np.frombuffer((build / "zoom-swap.bin").read_bytes(), dtype=np.uint8))
    program = build / "player.prg"
    program_hash = sha(program.read_bytes())
    native = load_monitor_api()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = [str(vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100", "+warp",
        "+autostart-warp", "+confirmonexit", "-sounddev", "dummy", "+refreshonbreak", "+binarymonitor",
        "-initbreak", "reset", "-autostartprgmode", "1", "-autostart", str(program), "-VICIIfilter", "0",
        "-VICIIextpal", "-VICIIpalette", str(REPO / "palettes/colodore.vpl"), "-VICIIsaturation", "1000",
        "-VICIIcontrast", "1000", "-VICIIbrightness", "1000", "-VICIIgamma", "1000", "-remotemonitor",
        "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report = {"passed": False, "programSha256": program_hash, "scope": "Separate monitor-input boundary cases; scene/crop controls select valid renderer states. Not a phase-duration or FPS benchmark.",
        "priorGlyph": 0, "priorForeground": 2, "priorPixelsBlack": True, "nextObject": "ball-lit", "nextPose": 1}
    process = connection = monitor = None
    events = ("presented", "render_end", "commit_start", "commit_end", "field_complete")
    committed = False
    first_field_verified = False
    current_image = Image.new("RGB", (320, 200))
    pending_image = None
    pending_serial = None
    pending_mode = None
    pending_crop = None
    action_ready = False
    action_index = 0
    wanted = stress_field = None
    stress_actions = [
        (34, 5, 35, 6, (12, 5), (10, 6)),
        (34, 5, 35, 6, (0, 0), (0, 1)),
        (28, 2, 29, 6, (18, 13), (20, 13)),
        (24, 0, 24, 0, (10, 6), (10, 6)),
    ] if crop_stress else []
    report["cropStress"] = []
    color_watch = None
    def ram_state():
        monitor.run("bank ram")
        ram = monitor.dump(output / "last-ram.bin", 0, 0x3fff)
        monitor.run("bank cpu")
        return ram
    def put(first, values):
        for at in range(0, len(values), 32):
            monitor.run(f"> ${first + at:04x} " + " ".join(f"${value:02x}" for value in values[at:at + 32]))
    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            report["ownedPid"] = process.pid
            connection = native.connect(process, port)
            monitor = native.Monitor(connection)
            monitor.run("sidefx off")
            monitor.checkpoint(labels["presented"])
            monitor.run("x")
            assert monitor.registers()["pc"] == labels["presented"]
            ram = ram_state()
            assert ram[0x3000:0x3200] == oracle.font
            front = ram[labels["front_screen_hi"]] << 8
            monitor.run("bank ram")
            put(front, bytes(1000))
            put(0x0c00, bytes([2]) * 1024)
            for name, value in (("object_id", 2), ("step_index", 24), ("mode", 0), ("film_frame", 0),
                                ("phase", 0), ("mode_due", 0), ("zoom_x", 10), ("zoom_y", 6)):
                put(labels[name], bytes([value]))
            put(labels["film_serial"], bytes(2))
            put(labels["mode_fields_left"], (501).to_bytes(2, "little"))
            monitor.run("bank io")
            put(0xd800, bytes([2]) * 1024)
            monitor.run("bank cpu")
            result = monitor.run("break store d800 dbe7")
            color_watch = int(re.search(r"(?:BREAK|WATCH):\s*(\d+)", result)[1])
            for name in events[1:]:
                monitor.checkpoint(labels[name])
            for event_number in range(300):
                monitor.run("x")
                registers = monitor.registers()
                event = next((name for name in events if labels[name] == registers["pc"]), None)
                assert event is not None, "Foreground hardware changed before commit"
                if event == "presented":
                    if color_watch is not None:
                        monitor.run(f"delete {color_watch}")
                    result = monitor.run("break store d800 dbe7")
                    color_watch = int(re.search(r"(?:BREAK|WATCH):\s*(\d+)", result)[1])
                    if action_ready:
                        ram = ram_state()
                        base, base_mode, target, target_mode, center, crop = stress_actions[action_index]
                        serial_at = labels["film_serial"]
                        serial = ram[serial_at] + 256 * ram[serial_at + 1] + 1
                        wanted = {"serial": serial, "step": target, "mode": target_mode, "crop": crop}
                        monitor.run("bank ram")
                        for name, value in (("step_index", base), ("mode", base_mode), ("zoom_x", center[0]),
                                            ("zoom_y", center[1]), ("mode_due", int(target != base))):
                            put(labels[name], bytes([value]))
                        put(labels["mode_fields_left"], (0 if target != base else 501).to_bytes(2, "little"))
                        monitor.run("bank cpu")
                        action_index += 1
                        action_ready = False
                elif event == "render_end":
                    ram = ram_state()
                    assert ram[labels["next_object"]] == 2
                    serial_at = labels["next_serial"]
                    pending_serial = ram[serial_at] + 256 * ram[serial_at + 1]
                    pending_mode = ram[labels["next_mode"]]
                    pending_crop = (ram[labels["latched_zoom_x"]], ram[labels["latched_zoom_y"]])
                    pending_image = oracle.image(2, pending_serial, pending_mode, pending_crop)
                    if wanted is not None:
                        assert (pending_serial, ram[labels["next_step"]], pending_mode, pending_crop) == (wanted["serial"], wanted["step"], wanted["mode"], wanted["crop"])
                    back = ram[labels["back_screen_hi"]] << 8
                    actual = image_from_ram(oracle, ram, back, ram[0x0c00:0x0fe8], pending_mode)
                    assert ImageChops.difference(actual, pending_image).getbbox() is None, ("Sparse-clear prepared image", pending_serial, pending_mode, pending_crop)
                    if not committed:
                        assert ram[labels["next_film_frame"]] == 1 and pending_mode == 0
                        at = labels["color_changed_count"]
                        report["dirtyForegrounds"] = ram[at] + 256 * ram[at + 1]
                        assert report["dirtyForegrounds"] >= 256
                elif event == "commit_start":
                    assert color_watch is not None
                    monitor.run(f"delete {color_watch}")
                    color_watch = None
                elif event == "commit_end":
                    ram = ram_state()
                    assert ram[labels["object_id"]] == 2 and ram[labels["film_frame"]] == pose(pending_serial)
                    front = ram[labels["front_screen_hi"]] << 8
                    monitor.run("bank io")
                    colors = bytes(v & 15 for v in monitor.dump(output / "colors.bin", 0xd800, 0xdbe7))
                    monitor.run("bank cpu")
                    image = image_from_ram(oracle, ram, front, colors, pending_mode)
                    assert ImageChops.difference(image, pending_image).getbbox() is None
                    current_image = pending_image
                    if not committed:
                        assert ram[labels["color_fallback"]] == 1
                        actual_changes = sum(color != 2 for color in colors)
                        assert actual_changes == report["dirtyForegrounds"]
                        retained = sum((code & 63) == 0 and color == 2 for code, color in zip(ram[front:front + 1000], colors))
                        assert retained > 0
                        report.update(actualForegroundChanges=actual_changes, unusedForeground2RetainedCells=retained, sequentialFallback=True)
                    if wanted is not None:
                        stress_field = wanted
                        wanted = None
                    committed = True
                elif event == "field_complete":
                    picture = output / ("first-reactivated-field.png" if committed and not first_field_verified else f"boundary-field-{event_number:03d}.png")
                    monitor.run(f'scrsh "{picture}" 2')
                    compare_scanout(picture, current_image)
                    if committed and not first_field_verified:
                        report.update(firstCompletedFieldExact=True, noVisibleColorTearing=True, screenshot=picture.name)
                        first_field_verified = True
                        if not crop_stress:
                            report["passed"] = True
                            break
                        action_ready = True
                    elif stress_field is not None:
                        report["cropStress"].append({**stress_field, "screenshot": picture.name, "firstCompletedFieldExact": True})
                        stress_field = None
                        if action_index == len(stress_actions):
                            report["passed"] = True
                            break
                        action_ready = True
            else:
                raise AssertionError("Bounded unused-foreground scenario did not finish")
            assert sha(program.read_bytes()) == program_hash
        except BaseException as error:
            report["error"] = repr(error)
            raise
        finally:
            if monitor:
                (output / "monitor.log").write_text("\n".join(monitor.transcript))
            if connection:
                try:
                    connection.sendall(b"quit\n")
                except OSError:
                    pass
                connection.close()
            if process and process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            report["ownedProcessExitCode"] = process.returncode if process else None
            (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def verify(build, data, output, vice, full_base_timers=False, baseline=None):
    build, data, output = build.resolve(), data.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((build / "build.json").read_text())
    labels = labels_from(build / "main.sym")
    events = ("presented", "prepare_start", "render_start", "render_end", "commit_start",
              "commit_color_start", "commit_color_end", "commit_end", "field_complete")
    queue_events = tuple(name for name in ("color_queue_start", "color_queue_end") if name in labels)
    clear_events = tuple(name for name in ("clear_start", "clear_end") if name in labels)
    events += queue_events + clear_events
    required = set(events) | {"object_id", "next_object", "mode", "next_mode", "film_frame", "next_film_frame",
        "film_serial", "next_serial", "step_index", "next_step", "mode_fields_left", "mode_due", "field_counter",
        "front_screen_hi", "back_screen_hi", "active_zoom_x", "active_zoom_y", "latched_zoom_x", "latched_zoom_y"}
    assert required <= labels.keys(), sorted(required - labels.keys())
    assert len({labels[name] for name in events}) == len(events), "Aliased observable stages"
    assert manifest["stepMode"] == [script(step)[1] for step in range(40)]
    assert manifest["stepObject"] == [script(step)[0] for step in range(40)]
    object_names = [obj["name"] for obj in manifest["objects"]]
    assert object_names == ["star-lit", "cube-lit", "ball-lit"]
    oracle = Oracle(data, object_names)
    zoom = oracle.validate_zoom(np.frombuffer((build / "zoom-map.bin").read_bytes(), dtype=np.uint8),
                                np.frombuffer((build / "zoom-swap.bin").read_bytes(), dtype=np.uint8))
    native = load_monitor_api()
    program = build / "player.prg"
    program_hash = sha(program.read_bytes())
    source_hashes = {str(p.relative_to(data)): sha(p.read_bytes()) for p in data.rglob("*") if p.is_file()}
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    palette = REPO / "palettes/colodore.vpl"
    command = [str(vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100", "+warp",
        "+autostart-warp", "+confirmonexit", "-sounddev", "dummy", "+refreshonbreak", "+binarymonitor",
        "-initbreak", "reset", "-autostartprgmode", "1", "-autostart", str(program), "-VICIIfilter", "0",
        "-VICIIextpal", "-VICIIpalette", str(palette), "-VICIIsaturation", "1000", "-VICIIcontrast", "1000",
        "-VICIIbrightness", "1000", "-VICIIgamma", "1000", "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    report = {"passed": False, "programSha256": program_hash, "fontSha256": FONT_SHA, "sourceData": str(data),
        "scope": "Actual completed PAL fields against original ECM movies; base timers may be shortened after samples, flashes never shortened.",
        "zoom": zoom, "fields": [], "commits": [], "stages": [], "phaseStarts": [], "timerAdjustments": [], "command": command}
    process = connection = monitor = None
    active_step = active_serial = active_ordinal = 0
    active_crop = (10, 6)
    expected = oracle.image(0, 0, 0)
    pending = None
    color_start = render_start = prepare_start = commit_start = queue_start = clear_start = None
    color_cycles = preparation_cycles = render_cycles = queue_cycles = clear_cycles = None
    front_watch = None
    color_watch = None
    previous_screen = bytes(1000)
    previous_colors = bytes(1000)
    blank_foreground = {"blankToNonblankCells": 0, "reactivationsChangingForeground": 0,
                        "reactivationsKeepingForeground": 0, "blankCellsRetainingNonzeroForeground": 0}
    color_paths = {"grouped": 0, "sequentialFallback": 0}
    initial = True
    last_field_clock = last_counter = None
    active_screens = set()
    adjusted = set()
    crop_by_flash = {}
    def word(ram, name):
        at = labels[name]
        return ram[at] + 256 * ram[at + 1]
    def state():
        monitor.run("bank ram")
        ram = monitor.dump(output / "last-ram.bin", 0, 0x3fff)
        monitor.run("bank cpu")
        return ram
    def color_ram():
        monitor.run("bank io")
        colors = bytes(value & 15 for value in monitor.dump(output / "last-colors.bin", 0xd800, 0xdbe7))
        monitor.run("bank cpu")
        return colors
    def check_active(ram):
        obj, mode = script(active_step)
        assert (ram[labels["object_id"]], ram[labels["mode"]], ram[labels["film_frame"]], word(ram, "film_serial")) == (obj, mode, pose(active_serial), active_serial)
        assert ram[labels["step_index"]] == active_step
        assert ram[0x3000:0x3200] == oracle.font, "Frozen font changed"
    def stage_pending(ram):
        step, serial = ram[labels["next_step"]], word(ram, "next_serial")
        obj, mode = script(step)
        assert step in (active_step, (active_step + 1) % 40)
        assert (ram[labels["next_object"]], ram[labels["next_mode"]], ram[labels["next_film_frame"]]) == (obj, mode, pose(serial))
        assert serial == (1 if obj != script(active_step)[0] else active_serial + 1), "Source animation must advance exactly one stored pose"
        crop = (ram[labels["latched_zoom_x"]], ram[labels["latched_zoom_y"]])
        assert 0 <= crop[0] <= 20 and 0 <= crop[1] <= 13
        if mode == 6:
            if step in crop_by_flash:
                assert crop == crop_by_flash[step], "Crop moved during a flash"
            else:
                crop_by_flash[step] = crop
        return step, serial, crop, oracle.image(obj, serial, mode, crop)
    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            report["ownedPid"] = process.pid
            connection = native.connect(process, port)
            monitor = native.Monitor(connection)
            monitor.run("sidefx off")
            for name in events:
                monitor.checkpoint(labels[name])
            monitor.run("x")
            for event_count in range(100000 if full_base_timers else 30000):
                registers = monitor.registers()
                event = next((name for name in events if labels[name] == registers["pc"]), None)
                assert event is not None, ("Unexpected protected memory write or breakpoint", registers)
                report["stages"].append({"event": event, **registers})
                if event == "presented":
                    ram = state()
                    check_active(ram)
                    if initial:
                        report["phaseStarts"].append({"ordinal": 0, "step": 0, "field": word(ram, "field_counter"), "serial": 0, "clock": registers["clock"]})
                        initial = False
                        for region in manifest.get("sourceRegions", []):
                            monitor.run("bank ram")
                            raw = monitor.dump(output / "loaded-region.bin", region["start"], region["end"] - 1)
                            assert raw == (build / region["file"]).read_bytes(), ("Native source load", region["file"])
                            monitor.run("bank cpu")
                            monitor.run(f"break store {region['start']:04x} {region['end']-1:04x}")
                        monitor.run("break store 3000 31ff")
                        previous_screen = bytes(ram[(ram[labels["front_screen_hi"]] << 8):(ram[labels["front_screen_hi"]] << 8) + 1000])
                        previous_colors = color_ram()
                    if front_watch is not None:
                        monitor.run(f"delete {front_watch}")
                    front = ram[labels["front_screen_hi"]] << 8
                    result = monitor.run(f"break store {front:04x} {front+1023:04x}")
                    front_watch = int(re.search(r"(?:BREAK|WATCH):\s*(\d+)", result)[1])
                    if color_watch is not None:
                        monitor.run(f"delete {color_watch}")
                    result = monitor.run("break store d800 dbe7")
                    color_watch = int(re.search(r"(?:BREAK|WATCH):\s*(\d+)", result)[1])
                    if not full_base_timers and active_step % 2 == 0 and active_ordinal not in adjusted and len(active_screens) >= 3:
                        # Every normal base runs naturally through its full
                        # pose cycle. Other bases retain preparation margin
                        # while skipping the uneventful part of the hold.
                        if active_step not in (0, 12, 24):
                            remaining = max(16, ram[labels["transition_margin"]]) if "transition_margin" in labels else 16
                            at = labels["mode_fields_left"]
                            monitor.run(f"> ${at:04x} ${remaining & 255:02x} ${remaining >> 8:02x}")
                            monitor.run(f"> ${labels['mode_due']:04x} $00")
                            report["timerAdjustments"].append({"step": active_step, "remaining": remaining, "field": word(ram, "field_counter"), "sourceTimeUnchanged": True})
                            adjusted.add(active_ordinal)
                    if active_ordinal == 40 and len(active_screens) >= 3:
                        break
                elif event == "prepare_start":
                    prepare_start = registers["clock"]
                    queue_cycles = 0
                    clear_cycles = 0
                elif event == "clear_start":
                    clear_start = registers["clock"]
                elif event == "clear_end":
                    assert clear_start is not None
                    clear_cycles = registers["clock"] - clear_start
                elif event == "render_start":
                    render_start = registers["clock"]
                elif event == "render_end":
                    preparation_cycles = registers["clock"] - prepare_start
                    render_cycles = registers["clock"] - render_start
                    ram = state()
                    pending = stage_pending(ram)
                    back = ram[labels["back_screen_hi"]] << 8
                    image = image_from_ram(oracle, ram, back, ram[0x0c00:0x0fe8], script(pending[0])[1])
                    difference = ImageChops.difference(image, pending[3])
                    if difference.getbbox():
                        image.save(output / "failed-prepared.png")
                        pending[3].save(output / "failed-prepared-expected.png")
                        difference.save(output / "failed-prepared-difference.png")
                        raise AssertionError(("Prepared effect differs", pending[:3], difference.getbbox()))
                elif event == "commit_start":
                    commit_start = registers["clock"]
                    assert pending is not None
                    if front_watch is not None:
                        monitor.run(f"delete {front_watch}")
                        front_watch = None
                    if color_watch is not None:
                        monitor.run(f"delete {color_watch}")
                        color_watch = None
                elif event == "color_queue_start":
                    queue_start = registers["clock"]
                elif event == "color_queue_end":
                    assert queue_start is not None
                    queue_cycles = registers["clock"] - queue_start
                    preparation_cycles = registers["clock"] - prepare_start
                elif event == "commit_color_start":
                    color_start = registers["clock"]
                elif event == "commit_color_end":
                    assert color_start is not None
                    color_cycles = registers["clock"] - color_start
                elif event == "commit_end":
                    ram = state()
                    old_step = active_step
                    active_step, active_serial, active_crop, expected = pending
                    if active_step != old_step:
                        active_ordinal += 1
                        assert active_step == active_ordinal % 40
                        active_screens = set()
                        report["phaseStarts"].append({"ordinal": active_ordinal, "step": active_step, "field": word(ram, "field_counter"), "serial": active_serial, "clock": registers["clock"]})
                    check_active(ram)
                    front = ram[labels["front_screen_hi"]] << 8
                    hardware_colors = color_ram()
                    actual_ram = image_from_ram(oracle, ram, front, hardware_colors, script(active_step)[1])
                    assert ImageChops.difference(actual_ram, expected).getbbox() is None, "Published screen/ColorRAM differs"
                    new_screen = bytes(ram[front:front + 1000])
                    for old_code, new_code, old_color, new_color in zip(previous_screen, new_screen, previous_colors, hardware_colors):
                        if (old_code & 63) == 0 and (new_code & 63) != 0:
                            blank_foreground["blankToNonblankCells"] += 1
                            key = "reactivationsChangingForeground" if old_color != new_color else "reactivationsKeepingForeground"
                            blank_foreground[key] += 1
                        if (new_code & 63) == 0 and old_color == new_color and new_color != 0:
                            blank_foreground["blankCellsRetainingNonzeroForeground"] += 1
                    actual_color_changes = sum(before != after for before, after in zip(previous_colors, hardware_colors))
                    previous_screen, previous_colors = new_screen, hardware_colors
                    dirty_count = word(ram, "color_changed_count") if "color_changed_count" in labels else None
                    fallback = bool(ram[labels["color_fallback"]]) if "color_fallback" in labels else None
                    if dirty_count is not None:
                        assert dirty_count == actual_color_changes, ("Dirty-color queue differs from actual shared ColorRAM changes", dirty_count, actual_color_changes)
                        color_paths["sequentialFallback" if fallback else "grouped"] += 1
                    report["commits"].append({"ordinal": active_ordinal, "step": active_step, "serial": active_serial,
                        "clock": registers["clock"], "commitWallCycles": registers["clock"] - commit_start,
                        "preparationWallCycles": preparation_cycles, "renderWallCycles": render_cycles,
                        "colorCopyWallCycles": color_cycles,
                        "colorQueueWallCycles": queue_cycles, "actualForegroundChanges": actual_color_changes,
                        "clearWallCycles": clear_cycles,
                        "colorDirtyCount": dirty_count, "colorSequentialFallback": fallback,
                        "crop": list(active_crop), "endRaster": registers["raster"]})
                    pending = None
                elif event == "field_complete":
                    ram = state()
                    check_active(ram)
                    counter = word(ram, "field_counter")
                    if last_counter is not None:
                        assert counter == (last_counter + 1) & 0xffff
                        assert abs(registers["clock"] - last_field_clock - PAL_FRAME_CYCLES) <= 126
                    last_counter, last_field_clock = counter, registers["clock"]
                    assert 256 <= registers["raster"] <= 258
                    picture = output / f"field-{len(report['fields']):04d}-step-{active_step:02d}-pose-{pose(active_serial):02d}.png"
                    monitor.run(f'scrsh "{picture}" 2')
                    comparison = compare_scanout(picture, expected)
                    active_screens.add(active_serial)
                    report["fields"].append({"ordinal": active_ordinal, "step": active_step, "object": script(active_step)[0],
                        "mode": script(active_step)[1], "serial": active_serial, "fieldCounter": counter,
                        "clock": registers["clock"], "screenshot": picture.name, **comparison})
                    if len(report["fields"]) % 200 == 0:
                        print(json.dumps({"nativeFields": len(report["fields"]), "step": active_step, "phases": active_ordinal}), flush=True)
                    assert len(report["fields"]) < (13000 if full_base_timers else 3000), "Bounded proof exceeded field limit"
                monitor.run("x")
            else:
                raise AssertionError("Bounded native event proof did not finish")
            assert [phase["step"] for phase in report["phaseStarts"]] == list(range(40)) + [0]
            starts = report["phaseStarts"]
            flashes = [starts[index + 1]["field"] - starts[index]["field"] for index in range(1, 40, 2)]
            assert flashes == [25] * 20, flashes
            normal_durations = {str(step): starts[step + 1]["field"] - starts[step]["field"] for step in (0, 12, 24)}
            assert set(normal_durations.values()) == {501}
            normal_poses = {str(obj): sorted({pose(field["serial"]) for field in report["fields"]
                if field["step"] == obj * 12 and field["ordinal"] < 40 and field["serial"] > 0}) for obj in range(3)}
            assert all(poses == list(range(1, 49)) for poses in normal_poses.values()), normal_poses
            modes_seen = {(field["object"], field["mode"]) for field in report["fields"]}
            assert {(obj, mode) for obj in range(3) for mode in range(7)} <= modes_seen
            assert (0, 7) in modes_seen and (0, 8) in modes_seen
            assert blank_foreground["reactivationsChangingForeground"] > 0, "No retained-foreground reactivation requiring a color change was exercised"
            assert blank_foreground["reactivationsKeepingForeground"] > 0
            timing = {}
            for obj, mode in sorted(modes_seen):
                records = [c for c in report["commits"] if script(c["step"]) == (obj, mode)]
                intervals = [b["clock"] - a["clock"] for a, b in zip(records, records[1:]) if b["ordinal"] == a["ordinal"]]
                if intervals:
                    timing[f"{object_names[obj]}/{mode}"] = {"intervals": len(intervals), "fps": PAL_CLOCK / statistics.mean(intervals),
                        "minWallCycles": min(intervals), "maxWallCycles": max(intervals)}
            assert sha(program.read_bytes()) == program_hash
            assert all(sha((data / name).read_bytes()) == digest for name, digest in source_hashes.items())
            comparison = None
            if baseline:
                before = json.loads(baseline.read_text())
                assert before["passed"] and before["fontSha256"] == FONT_SHA
                comparison = {"baselineProof": str(baseline.resolve()), "baselineProgramSha256": before["programSha256"], "modes": {}}
                for name, after in timing.items():
                    if name in before["measuredTiming"]:
                        old_fps = before["measuredTiming"][name]["fps"]
                        comparison["modes"][name] = {"beforeFPS": old_fps, "afterFPS": after["fps"], "changePercent": (after["fps"] / old_fps - 1) * 100,
                            "beforeIntervals": before["measuredTiming"][name]["intervals"], "afterIntervals": after["intervals"]}
                fair_normals = before.get("normalBaseDurationsFields") == {"0": 501, "12": 501, "24": 501}
                comparison["scope"] = ("Both builds run all three normal phases for501fields and cover48poses. Other effects are samples along different source-time trajectories, not paired-pose benchmarks."
                    if fair_normals else "All three current normal phases run501fields and cover48poses. Earlier cube/ball baselines contain shorter samples, so those ratios are observed-run comparisons, not paired all-pose benchmarks.")
            contact = Image.new("RGB", (1280, 448), (20, 22, 18))
            draw = ImageDraw.Draw(contact)
            selections = [(0, 0, "Star"), (1, 0, "Cube"), (2, 0, "Ball"), (0, 1, "Wave"),
                          (1, 2, "Checker history"), (0, 5, "Mirror H/V"), (2, 6, "Fixed 2x flash"), (0, 8, "Mixed quadrants")]
            contact_fields = []
            for index, (obj, mode, title) in enumerate(selections):
                selected = next(field for field in reversed(report["fields"]) if field["object"] == obj and field["mode"] == mode and field["serial"] > 0)
                actual = Image.open(output / selected["screenshot"]).convert("RGB").crop((32, 35, 352, 235))
                actual = actual.resize((300, 200), Image.Resampling.NEAREST)
                x, y = (index % 4) * 320, (index // 4) * 224
                draw.text((x + 10, y + 4), f"{title} / pose {pose(selected['serial'])}", fill=(225, 235, 210))
                contact.paste(actual, (x + 10, y + 24))
                contact_fields.append({"title": title, "screenshot": selected["screenshot"]})
            contact.save(output / "contact.png")
            report.update(passed=True, actualVisibleFieldsVerified=len(report["fields"]), comparedPixels=len(report["fields"]) * 64000,
                flashDurationsFields=flashes, firstBaseDurationFields=501, modesSeen=[list(item) for item in sorted(modes_seen)],
                normalBaseDurationsFields=normal_durations, normalPosesVerified=normal_poses,
                measuredTiming=timing, sourceSerialAdvance=1, allComparedFieldsExact=True, noVisibleColorTearing=True,
                sourceDataUnchanged=True, nativeTimingIncludesVICStallsAndColorCommit=True,
                colorQueueIncludedInTiming=True, blankForegroundReuse=blank_foreground, beforeAfterTiming=comparison,
                colorCommitPaths=color_paths,
                contact="contact.png", contactDisplayPixelAspect="59/63 approximated by 300/320", contactFields=contact_fields)
        except BaseException as error:
            report["error"] = repr(error)
            raise
        finally:
            if monitor:
                (output / "monitor.log").write_text("\n".join(monitor.transcript))
            if connection:
                try:
                    connection.sendall(b"quit\n")
                except OSError:
                    pass
                connection.close()
            if process and process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            report["ownedProcessExitCode"] = process.returncode if process else None
            (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    if "color_changed_count" in labels:
        try:
            assert color_paths["grouped"] > 0
            report["unusedForegroundBoundary"] = verify_unused_foreground_boundary(build, data, output / "unused-foreground-boundary", vice, crop_stress=True)
            report["sequentialFallbackNativeCases"] = color_paths["sequentialFallback"] + int(report["unusedForegroundBoundary"]["sequentialFallback"])
            assert report["sequentialFallbackNativeCases"] > 0
        except BaseException as error:
            report["passed"] = False
            report["error"] = repr(error)
            (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
            raise
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key not in ("fields", "stages", "commits", "command", "phaseStarts")}, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=HERE / "build")
    parser.add_argument("--data", type=Path, default=HERE / "generated-symmetric")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/bin/x64sc"))
    parser.add_argument("--full-base-timers", action="store_true", help="Observe all ten-second bases naturally instead of shortening later holds.")
    default_baseline = HERE / "build-before-fast-rows/native-check/verification.json"
    parser.add_argument("--baseline", type=Path, default=default_baseline if default_baseline.exists() else None,
                        help="Prior native verification.json for an observed FPS comparison.")
    args = parser.parse_args()
    verify(args.build, args.data, args.output or args.build / "native-check", args.vice, args.full_base_timers, args.baseline)


if __name__ == "__main__":
    main()

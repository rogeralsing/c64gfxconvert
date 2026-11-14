"""Verify ordinary VICE PRG loading and restored native RAM before playback.

The monitor only installs checkpoints and continues execution. VICE performs
the LOAD and RUN through its normal autostart path, without RAM injection.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

import native_support as support


def _compare_ram(native: bytes, load: int, snapshots: list[tuple[int, Path]],
                 arena: tuple[int, int]) -> dict:
    compared, mismatches, examples = 0, 0, []
    for start, path in snapshots:
        actual = path.read_bytes()
        wanted = native[start - load:start - load + len(actual)]
        if len(wanted) != len(actual):
            raise ValueError(f"RAM snapshot exceeds native image: {path}")
        for index, (observed, expected) in enumerate(zip(actual, wanted)):
            address = start + index
            if arena[0] <= address < arena[1]:
                continue
            compared += 1
            if observed != expected:
                mismatches += 1
                if len(examples) < 16:
                    examples.append({"address": address, "observed": observed,
                                     "expected": expected})
    return {"passed": mismatches == 0, "bytes_compared": compared,
            "excluded_loader_arena": list(arena), "mismatched_bytes": mismatches,
            "first_mismatches": examples,
            "scope": "Native RAM at loader_done, before original player entry. I/O is excluded; the declared loader arena is the only excluded RAM."}


def verify(build: dict, native_program: Path, out: Path, *, mode: int = 0,
           full: bool = False, ticks: int = 300, startup_seconds: float = 600,
           timeout: float | None = None) -> dict:
    """Run virtual-filesystem or disk autostart and compare restored native RAM."""
    if mode not in (0, 2):
        raise ValueError("Use ordinary-load mode0 or disk mode2; injection is not a regression proof")
    if ticks < 2 or startup_seconds <= 0:
        raise ValueError("Expected at least two ticks and a positive startup limit")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    loader = build["startup_loader"]
    labels = build["symbols"]
    for name in ("loader_enter", "loader_done", "loader_payload", "loader_end"):
        if name not in labels:
            raise ValueError(f"Packaged build has no {name} symbol")
    program, native_program = Path(build["program"]).resolve(), Path(native_program).resolve()
    if support.digest(program) != build["program_sha256"]:
        raise ValueError("Packaged PRG differs from build receipt")
    if support.digest(native_program) != loader["native_sha256"]:
        raise ValueError("Native PRG differs from packaging receipt")
    original = native_program.read_bytes()
    load = int.from_bytes(original[:2], "little")
    native = original[2:]
    native_end = load + len(native)
    if load != 0x0801 or native_end != loader["native_end_exclusive"]:
        raise ValueError("Unexpected native image range")
    if not 0xe000 < native_end <= 0xff00:
        raise ValueError("Native image does not have the expected high-RAM tail")
    arena = tuple(loader["arena"])
    frame_count = int(labels["FRAME_COUNT"])
    full_run = full or ticks >= frame_count
    expected_frames = frame_count if full_run else ticks
    stop = labels["done"] if full_run else labels["fill_begin"]
    condition = "" if full_run else (
        f" if @ram:$000a == ${expected_frames & 255:02x}"
        f" && @ram:$000b == ${expected_frames >> 8:02x}")
    media, stats, log, monitor = (out / name for name in
                                ("registers.txt", "stats.bin", "monitor.log", "startup.mon"))
    snapshots = [(0x0801, out / "restored-low.bin"), (0xe000, out / "restored-high.bin")]
    for path in (media, stats, log, *(path for _, path in snapshots)):
        path.unlink(missing_ok=True)
    commands = [f'logname "{log}"', "log on", "bank ram",
                f'break exec ${labels["loader_done"]:04x}',
                f'break exec ${stop:04x}{condition}', "g", "r", "stopwatch",
                f'bsave "{snapshots[0][1]}" 0 $0801 $cfff',
                f'bsave "{snapshots[1][1]}" 0 $e000 ${native_end - 1:04x}',
                "delete 1", "g", "r", "stopwatch",
                f'bsave "{stats}" 0 $0002 $000d', "log off", "quit"]
    monitor.write_text("\n".join(commands) + "\n")
    duration = expected_frames / 50
    drive_option = "+drive8truedrive" if mode == 0 else "-drive8truedrive"
    command = ["rtk", "proxy", *support.profile().vice_command(), drive_option, "-console", "-seed", "1",
               "-initbreak", "reset", "-moncommands", str(monitor),
               "-autostartprgmode", str(mode), "-autostart", str(program),
               "-autostartprgdiskimage", str(out / "autostart.d64"),
               "-sounddev", "dump", "-soundarg", str(media), "-warp",
               "-limitcycles", str(round((startup_seconds + duration + 15) * support.CLOCK))]
    result = {"passed": False, "mode": mode, "program_sha256": build["program_sha256"],
              "native_sha256": loader["native_sha256"], "command": command,
              "profile": support.profile().PROFILE, "full_performance": full_run,
              "expected_source_frames": expected_frames,
              "manual_load_or_SYS_or_addressed_g": False,
              "loader_done": labels["loader_done"], "stop_pc": stop}
    receipt_path = out / "verification.json"
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=timeout or max(120, startup_seconds + duration + 120))
        (out / "vice.log").write_text(completed.stdout + completed.stderr)
        result["vice_exit_code"] = completed.returncode
        if completed.returncode or not all(p.exists() for p in (stats, media, log, *(p for _, p in snapshots))):
            raise RuntimeError("Ordinary autostart did not reach both regression checkpoints")
        sizes = (0xd000 - 0x0801, native_end - 0xe000)
        if any(path.stat().st_size != size for (_, path), size in zip(snapshots, sizes)):
            raise ValueError("Monitor RAM snapshot has an unexpected length")
        pcs = {int(value, 16) for value in re.findall(
            r"^(?:\.C:|\.;)([0-9a-fA-F]{4})(?:\s|$)", log.read_text(), re.MULTILINE)}
        if labels["loader_done"] not in pcs or stop not in pcs:
            raise ValueError("Monitor log does not confirm both expected checkpoint PCs")
        result["restored_native_ram"] = _compare_ram(native, load, snapshots, arena)
        counters = stats.read_bytes()
        if len(counters) != 12:
            raise ValueError("Incomplete native counter snapshot")
        underruns = int.from_bytes(counters[6:8], "little")
        generated = int.from_bytes(counters[8:10], "little")
        result.update(stats_hex=counters.hex(), generated_source_frames=generated,
                      underruns=underruns, media=str(media), media_sha256=support.digest(media),
                      monitor_log_sha256=support.digest(log), stats_file=str(stats))
        result["snapshots"] = [{"start": start, "bytes": path.stat().st_size,
                                "sha256": support.digest(path)} for start, path in snapshots]
        if not result["restored_native_ram"]["passed"]:
            raise ValueError("Ordinary LOAD did not restore the original native RAM bytes")
        if underruns or generated != expected_frames:
            raise ValueError(f"Native counters disagree: frames={generated}, underruns={underruns}")
        result["passed"] = True
        result["scope"] = ("Actual ordinary VICE autostart, RAM restoration before original entry and native completion counters. "
                           "The register dump remains available for the independent full musical trace verifier; no audio was captured or changed.")
    except Exception as error:
        result["error"] = str(error)
        support.save(receipt_path, result)
        raise
    support.save(receipt_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path, help="Packaged build.json")
    parser.add_argument("native", type=Path, help="Original, unchanged native.prg")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", type=int, choices=(0, 2), action="append",
                        help="Ordinary autostart mode; repeat to test both. Default: both")
    parser.add_argument("--full", action="store_true", help="Continue through the complete native performance")
    parser.add_argument("--ticks", type=int, default=300, help="Generated ticks for a short startup check")
    parser.add_argument("--startup-seconds", type=float, default=600)
    parser.add_argument("--timeout", type=float)
    args = parser.parse_args()
    build = json.loads(args.build.read_text())
    results = {str(mode): verify(build, args.native, args.out / f"mode-{mode}", mode=mode,
                                  full=args.full, ticks=args.ticks,
                                  startup_seconds=args.startup_seconds, timeout=args.timeout)
               for mode in dict.fromkeys(args.mode or (0, 2))}
    args.out.mkdir(parents=True, exist_ok=True)
    support.save(args.out / "verification.json", {"passed": True, "modes": results})
    print(json.dumps({"passed": True, "modes": list(results),
                      "receipt": str((args.out / "verification.json").resolve())}))


if __name__ == "__main__":
    main()

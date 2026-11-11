"""Record short MOD auditions with the unchanged accepted SID-voice player."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil

import audition_samples
from audition_instruments import recipe_for_instrument
import build_mod_arrangement as arrangement
import build_mod_hybrid as hybrid
from full_sid_score import prepare_full_sid
from verify_stream import verify

HERE = Path(__file__).resolve().parent
MOD = HERE.parent / "mod-hybrid"
DEFAULT_OUT = HERE / "results/auditions-20s"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def protected() -> dict:
    paths = [HERE / "mod-channel-hybrid-player.asm", HERE / "build_mod_hybrid.py",
             HERE / "instrument_library.py", HERE / "mod_sample_channel.py"]
    for folder, names in {"mod-channel-hybrid": ["player.prg", "hybrid.wav"],
                          "mod-channel": ["player.prg", "mod-channel.wav"],
                          "hyperbased": ["player.prg", "hybrid.wav"],
                          "hyperbased-full": ["player.prg", "hybrid.wav"]}.items():
        paths.extend(HERE / "results" / folder / name for name in names)
    for folder in ("cream-of-the-earth", "hyperbased", "hyperbased-full-sid"):
        paths.extend(path for path in (HERE / "instruments" / folder).iterdir() if path.is_file())
    for review in json.loads((HERE / "audition-listening.json").read_text())["songs"].values():
        solo = review.get("melody_solo", {})
        if solo.get("status") == "accepted":
            for kind in ("audio", "program"):
                path = HERE / solo[kind]
                if digest(path) != solo[f"{kind}_sha256"]:
                    raise ValueError(f"Accepted melody {kind} changed: {path}")
                paths.append(path)
    return {str(path.relative_to(HERE)): digest(path) for path in paths}


def implementation() -> dict:
    return {name: digest(HERE / name) for name in
            ("build_auditions.py", "audition_samples.py", "audition_instruments.py",
             "full_sid_score.py", "verify_stream.py", "mod-channel-hybrid-player.asm")}


def manual_recipe(mod: dict, identifier: int) -> tuple[dict, dict] | None:
    found = None
    for path in sorted((HERE / "audition-overrides").glob("*.json")):
        for song in json.loads(path.read_text()).get("songs", {}).values():
            if song.get("source_sha256") != mod["sha256"]:
                continue
            entry = song.get("instruments", {}).get(str(identifier))
            if entry is None:
                continue
            if found is not None:
                raise ValueError(f"Duplicate manual SID decision for source instrument {identifier}")
            recipe, analysis = copy.deepcopy(entry["recipe"]), copy.deepcopy(entry["analysis"])
            if recipe.get("source_instrument") != identifier:
                raise ValueError("Manual SID recipe has the wrong source instrument")
            template = analysis["template"]
            if digest(HERE / template["path"]) != template["sha256"]:
                raise ValueError("Manual SID template differs from its recorded identity")
            analysis.update(override_file=str(path.relative_to(HERE)), override_sha256=digest(path),
                            source_sha256=mod["sha256"], source_instrument=identifier,
                            listening_status="unreviewed", recommendation="sid")
            found = recipe, analysis
    return found


def approved_sid_variant(mod: dict, identifier: int) -> tuple[dict, dict] | None:
    library = HERE / "instruments/hyperbased-full-sid"
    document = json.loads((library / "library.json").read_text())
    if document["source"]["sha256"] != mod["sha256"]:
        return None
    for name in document["instruments"]:
        path = library / name
        recipe = json.loads(path.read_text())
        if recipe["source_instrument"] == identifier:
            return recipe, {"decision": "preserved_approved_sid_variant", "recommendation": "sid",
                            "template": {"path": str(path.relative_to(HERE)), "sha256": digest(path)},
                            "tradeoff": "Use the existing SID version of an instrument whose original sample also exists in the accepted library. No new SID program is invented."}
    return None


def drum_substitution(mod: dict, identifier: int, analysis: dict, names: dict) -> dict | None:
    """Reuse an approved drum sound only for a declared percussion role."""
    name = names.get(identifier, "").lower()
    template = None
    if re.search(r"snare|clap|\bsd\d*\b|clp", name):
        template = "04-snare.json"
    elif re.search(r"hi.?hat|cymbal|crash|ride|\bhh\d*\b|hihat", name):
        template = "05-hi-hat.json"
    elif re.search(r"kick|bass.?drum|\bbd\d*\b|basedrum", name):
        template = "01-kick.json"
    elif re.search(r"\btom\d*\b|conga|bongo|\bring\b|perc", name):
        template = "03-ring.json"
    if template is None:
        return None
    path = HERE / "instruments/cream-of-the-earth" / template
    recipe = json.loads(path.read_text())
    recipe.update(source_instrument=identifier, name=f"{names.get(identifier, identifier)}: approved drum substitution")
    analysis.update(decision="approved_drum_sound_substitution", recommendation="sid",
                    template={"path": str(path.relative_to(HERE)), "sha256": digest(path)},
                    tradeoff="Reuse the approved percussion recipe with original note/hit timing and period. This substitutes its sound; it does not claim a measured timbre match.")
    return recipe


def candidate_recipes(mod: dict, ticks: list, channels: list[int], names: dict, cache: dict) -> tuple[dict, dict, list[int]]:
    recipes, analyses, supported = {}, {}, []
    for channel in channels:
        states = [tick["channels"][channel - 1] for tick in ticks]
        identifiers = {state["playing_sample"] for state in states if state["playing_sample"] and state["volume"]}
        identifiers |= {state["loop_sample"] for state in states if state.get("loop_sample")
                        and mod["samples"][state["loop_sample"] - 1]["loop_length"] > 2}
        failed = False
        for identifier in sorted(identifiers):
            if not mod["samples"][identifier - 1]["length"]:
                continue
            if identifier not in cache:
                periods = [state["period"] for state in states if state["playing_sample"] == identifier and state["period"]]
                reference_period = sorted(periods)[len(periods) // 2] if periods else 428
                proposal = recipe_for_instrument(mod, identifier, reference_period=reference_period)
                recipe, analysis = proposal["recipe"], proposal["analysis"]
                if recipe is not None and (recipe.get("kind") == "sample" or "program" not in recipe):
                    alternative = approved_sid_variant(mod, identifier)
                    if alternative is not None:
                        recipe, extra = alternative
                        analysis.update(extra)
                    else:
                        recipe = None
                if recipe is None:
                    manual = manual_recipe(mod, identifier)
                    if manual is not None:
                        recipe, analysis = manual
                    else:
                        recipe = drum_substitution(mod, identifier, analysis, names)
                cache[identifier] = recipe, analysis
            recipe, analysis = cache[identifier]
            analyses[identifier] = analysis
            if recipe is None:
                failed = True
            else:
                recipes[identifier] = recipe
        if not failed:
            supported.append(channel)
    return recipes, analyses, supported


def sid_rows(mod: dict, timeline: list, start: int, samples: dict, channels: list[int],
             supported: list[int], recipes: dict, analyses: dict, source: dict, out: Path) -> tuple[list, dict, list]:
    library = out / "sid-instruments"; library.mkdir(exist_ok=True)
    files = []
    for identifier, recipe in sorted(recipes.items()):
        filename = f"{identifier:02d}-sid.json"
        save(library / filename, recipe)
        files.append(filename)
    settings = []
    for channel in channels:
        used = {tick["channels"][channel - 1]["playing_sample"] for tick in samples["frames"]}
        presets = [recipe for identifier, recipe in recipes.items() if identifier in used]
        sustain = max((preset.get("sustain", 1) for preset in presets), default=1)
        widths = [preset.get("pulse_width", 1966) for preset in presets if preset.get("program") in {"pulse", "arpeggio"}]
        settings.append({"sustain": sustain, "pulse_width": widths[0] if widths else 2048})
    save(library / "library.json", {"source": source, "instruments": files,
         "voice_levels": [item["sustain"] for item in settings],
         "voice_pulse_widths": [item["pulse_width"] for item in settings],
         "scope": "Short audition using accepted SID recipes and explicitly measured template substitutions. Source channels omitted when no defensible recipe is available."})
    prefix = copy.deepcopy(timeline[:start])
    for tick in prefix:
        for state in tick["channels"]:
            state["volume"] = 0
    selected = copy.deepcopy(samples["frames"])
    for tick in selected:
        for channel in channels:
            state = tick["channels"][channel - 1]
            identifier = state["playing_sample"]
            if channel not in supported or identifier and not mod["samples"][identifier - 1]["length"]:
                state["volume"] = 0
    result = prepare_full_sid(mod, prefix + selected, out / "sid-model", library_dir=library,
                              channels=tuple(channel - 1 for channel in channels), separate_percussion_hits=True)
    rows = result["rows"][len(prefix):]
    if len(rows) != samples["metadata"]["frames"]:
        raise ValueError("SID and PCM frame counts disagree")
    details = {"source_channels": supported, "physical_voice_settings": settings,
               "instrument_analysis": {str(identifier): analysis for identifier, analysis in analyses.items()},
               "host_preroll_ticks": len(prefix),
               "scope": "Source lifetime is advanced before the selected passage on the host; no preroll audio is included. Kept SID channels use original timing/periods and approved sound templates; their timbre/envelopes are approximations."}
    save(out / "sid-input.json", details)
    return rows, details, settings


def write_score(samples: dict, rows: list, settings: list, out: Path) -> None:
    lines = [f'.label FRAME_COUNT = {samples["metadata"]["frames"]}']
    for index, setting in enumerate(settings, 1):
        lines += [f'.label SID{index}_SUSTAIN = {setting["sustain"]}',
                  f'.label SID{index}_PULSE = {setting["pulse_width"]}']
    lines.append('.pc = $2000 "Reusable audition instruments"')
    banks = {bank["id"]: bank for bank in samples["banks"]}
    for bank in samples["banks"]:
        lines += [".align $100", f'{bank["label"]}:',
                  f'    .import source "{bank["path"].with_suffix(".asm")}"', f'{bank["label"]}_end:']
    lines += [".align $100", "silence_page:", "    .fill 256,128", "score:"]
    for frame, synth in zip(samples["score"], rows):
        label = banks[frame["bank"]]["label"]
        values = [frame["step"], frame["trigger"], f">{label}", f">{label}_end", frame["start_low"], *synth]
        lines.append("    .byte " + ",".join(map(str, values)))
    lines += ["program_end:", '.assert "Resident program below I/O", program_end <= $d000, true']
    (out / "data.asm").write_text("\n".join(lines) + "\n")


def run_song(song: dict, out_root: Path, capture: bool) -> dict:
    slug = song["slug"]
    out = out_root / slug; out.mkdir(parents=True, exist_ok=True)
    result = {"slug": slug, "status": "preparing", "listening_status": "unreviewed"}
    try:
        before = protected()
        source_hashes = implementation()
        receipt = json.loads((MOD / "sources" / f"{slug}.source.json").read_text())
        source = dict(receipt, title_slug=slug)
        mod = arrangement.source_mod(source, out)
        timeline = hybrid.base.build_timeline(mod)["ticks"]
        raw = Path(mod["source_path"]).read_bytes()
        names = {identifier: raw[20 + (identifier - 1) * 30:42 + (identifier - 1) * 30]
                 .rstrip(bytes([0])).decode("latin1") for identifier in range(1, 32)}
        cache, ranked = {}, []
        for index, candidate in enumerate(song["candidates"]):
            ticks = timeline[candidate["start_tick"]:candidate["end_tick"]]
            recipes, analyses, supported = candidate_recipes(mod, ticks, candidate["sid_channels"], names, cache)
            ranked.append((len(supported), -index, candidate, recipes, analyses, supported))
        failures, selected = [], None
        for _, _, candidate, recipes, analyses, supported in sorted(ranked, key=lambda item: item[:2], reverse=True):
            try:
                melody_channel = song.get("melody_channel")
                if melody_channel is not None and melody_channel not in {candidate["pcm_channel"], *supported}:
                    raise ValueError(f"Candidate omits the identified melody channel {melody_channel}; verify its solo before arranging accompaniment")
                ticks = timeline[candidate["start_tick"]:candidate["end_tick"]]
                samples = audition_samples.prepare(mod, ticks, candidate["pcm_channel"] - 1, out)
                rows, synth, settings = sid_rows(mod, timeline, candidate["start_tick"], samples,
                    candidate["sid_channels"], supported, recipes, analyses, source, out)
                write_score(samples, rows, settings, out)
                compiled = hybrid.base.reference.assemble("mod-channel-hybrid-player", out)
                selected = candidate, samples, rows, synth, compiled, supported
                break
            except (ValueError, RuntimeError) as error:
                failures.append({"candidate": candidate, "error": str(error)})
        if selected is None:
            raise ValueError(f"No supported candidate: {failures}")
        candidate, samples, rows, synth, compiled, supported = selected
        anchor = None
        if slug == "cream-of-the-earth" and candidate["start_tick"] == 896 and candidate["end_tick"] == 1896:
            expected_input = (HERE / "results/mod-channel/expected-input.bin").read_bytes()[:156389]
            reference = HERE / "results/mod-channel-hybrid"
            reference_build = json.loads((reference / "verification.json").read_text())["build"]
            reference_program = (reference / "player.prg").read_bytes()
            if hashlib.sha256(reference_program).hexdigest() != reference_build["program_sha256"]:
                raise ValueError("Accepted Cream program differs from its recorded identity")
            score_offset = reference_build["symbols"]["score"] - int.from_bytes(reference_program[:2], "little") + 2
            expected_rows = [list(reference_program[score_offset + index * 11 + 5:score_offset + index * 11 + 11])
                             for index in range(1000)]
            if (out / "expected-input.bin").read_bytes() != expected_input or rows != expected_rows:
                raise ValueError("Twenty-second Cream anchor changed the accepted instrument stream or SID score")
            anchor = {"sample_input_identical": True, "sid_values_identical": True, "sid_values_checked": 6000}
        shutil.copyfile(compiled["program"], out / "player.prg")
        used = {candidate["pcm_channel"], *supported}
        result.update(status="assembled", duration_s=samples["metadata"]["duration_s"],
                      source_range_s=samples["metadata"]["source_range_s"],
                      source_channels={"sampled": [candidate["pcm_channel"]], "sid": supported,
                                       "omitted": sorted(set(range(1, 5)) - used)},
                      source_sha256=mod["sha256"], pcm_input=samples["metadata"], synth_input=synth,
                      build=compiled, rejected_candidates=failures,
                      selected_candidate=candidate, implementation_sha256=source_hashes,
                      accepted_cream_anchor=anchor,
                      scope="A bounded MOD audition, using unchanged accepted SID-voice runtime and reusable original eight-bit sample banks. SID sounds reuse approved templates; omissions and approximations are explicit. Not a full-song or exact four-channel conversion.")
        if capture:
            recorded = hybrid.base.reference.capture(compiled, out / "player", samples["metadata"]["duration_s"])
            proof = verify(compiled, recorded, samples["metadata"], rows, out)
            audio = hybrid.base.reference.capture(compiled, out / "player", samples["metadata"]["duration_s"], audio=True)
            listening = hybrid.audio(audio, proof, samples["metadata"], out)
            audio_path = out_root / "audio" / f"{slug}-sid-preview.wav"
            audio_path.parent.mkdir(exist_ok=True)
            shutil.copyfile(out / "hybrid.wav", audio_path)
            program_path = out_root / "players" / f"{slug}-sid-preview.prg"
            program_path.parent.mkdir(exist_ok=True)
            shutil.copyfile(out / "player.prg", program_path)
            result.update(status="recorded", native_playback=proof, audio=listening,
                          audio_file=str(audio_path), program_file=str(program_path))
        if protected() != before:
            raise ValueError("An accepted instrument, player or reference artifact changed")
        if implementation() != source_hashes:
            raise ValueError("Audition implementation changed during the run; preserve output and reverify")
        result["accepted_references_preserved"] = before
    except Exception as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
    save(out / "audition.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--songs", nargs="+")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--jobs", type=int, choices=range(1, 4), default=2)
    args = parser.parse_args()
    all_songs = json.loads(args.plans.read_text())["songs"]
    songs = all_songs
    if args.songs:
        songs = [song for song in songs if song["slug"] in args.songs]
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    results = {}
    for song in all_songs:
        previous = out / song["slug"] / "audition.json"
        if previous.exists():
            results[song["slug"]] = json.loads(previous.read_text())

    def manifest() -> None:
        records = [results.get(song["slug"], {"slug": song["slug"], "status": "pending"}) for song in all_songs]
        save(out / "manifest.json", {"expected_songs": [song["slug"] for song in all_songs],
             "requested_songs": [song["slug"] for song in songs],
             "recorded_count": sum(item["status"] == "recorded" for item in records), "songs": records})

    manifest()
    with ProcessPoolExecutor(max_workers=args.jobs, max_tasks_per_child=1) as pool:
        futures = {pool.submit(run_song, song, out, args.capture): song for song in songs}
        for future in as_completed(futures):
            result = future.result(); results[result["slug"]] = result
            manifest()
            print(json.dumps({key: result.get(key) for key in ("slug", "status", "duration_s", "source_channels", "error")}), flush=True)
    if any(results[song["slug"]]["status"] == "failed" for song in songs):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

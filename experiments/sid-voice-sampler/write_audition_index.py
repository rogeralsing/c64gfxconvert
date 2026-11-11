"""Validate recorded audition artifacts and write their local listening index."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from html import escape
import json
from pathlib import Path

import soundfile as sf

HERE = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clock(value: float) -> str:
    centiseconds = round(value * 100)
    return f"{centiseconds // 6000}:{centiseconds // 100 % 60:02d}.{centiseconds % 100:02d}"


def title(slug: str) -> str:
    return {"4mats-madness": "4-Mat’s Madness", "livin-insanity": "Livin’ Insanity",
            "rink-a-dink": "Rink-a-dink"}.get(slug, slug.replace("-", " ").title())


def write(out: Path) -> dict:
    manifest = json.loads((out / "manifest.json").read_text())
    reviews = json.loads((HERE / "audition-listening.json").read_text())["songs"]
    expected = manifest["expected_songs"]
    if len(expected) != 19 or len(set(expected)) != 19:
        raise ValueError("The listening index requires all nineteen original MODs")
    records = {record["slug"]: record for record in manifest["songs"]}
    cards, markdown, identities, voice_counts = [], [], {}, Counter()
    sample_count = synth_count = 0
    profile = {"machine": "PAL C64", "sid_engine": 1, "sid_model": 2,
               "digiboost": True, "resampling": 2, "sample_rate": 22050}
    for slug in expected:
        record = records[slug]
        if record["status"] != "recorded":
            raise ValueError(f"{slug} has no verified actual recording")
        audio = out / "audio" / f"{slug}-sid-preview.wav"
        program = out / "players" / f"{slug}-sid-preview.prg"
        proof, pcm, build = record["native_playback"], record["pcm_input"], record["build"]
        info = sf.info(audio)
        if (sha(audio) != record["audio"]["output_sha256"] or sha(program) != build["program_sha256"]
                or proof["program_sha256"] != build["program_sha256"]
                or proof["profile"] != profile or record["audio"]["profile"] != profile
                or not proof["passed"] or not proof["all_sample_inputs_match_independent_model"]
                or proof["input_mismatches"] or not proof["ordinary_sid_sequence_matches"]
                or proof["ordinary_sid_write_mismatches"] or proof["synth_frame_timing_errors"]
                or proof["underruns"] or record["audio"]["underruns"]
                or proof["generated_frames"] != pcm["frames"]
                or proof["sample_gap_counts"] != {"126": pcm["input_codes"] - 1}
                or proof["d418_writes_during_music"]
                or info.samplerate != 22050 or info.channels != 1
                or info.frames != record["audio"]["frames"]
                or abs(info.duration - record["duration_s"]) > 1 / 22050
                or not 19 <= info.duration <= 20.1 or build["symbols"]["program_end"] > 0xD000):
            raise ValueError(f"{slug} has inconsistent audio, program, profile or playback proof")
        for relative, expected_sha in record["accepted_references_preserved"].items():
            if sha(HERE / relative) != expected_sha:
                raise ValueError(f"Accepted reference changed: {relative}")
        channels = record["source_channels"]
        voice_counts[len(channels["sampled"]) + len(channels["sid"]) ] += 1
        sample_count += proof["expected_samples"]; synth_count += proof["ordinary_sid_writes_checked"]
        start, end = record["source_range_s"]
        omitted = ", ".join(map(str, channels["omitted"]))
        kept = ", ".join(map(str, sorted(channels["sampled"] + channels["sid"])))
        sampled = ", ".join(map(str, channels["sampled"]))
        sid = ", ".join(map(str, channels["sid"])) or "ingen"
        review = reviews.get(slug, {})
        rejected = (review.get("status") == "rejected" and review.get("audio_sha256") == sha(audio)
                    and review.get("program_sha256") == sha(program))
        listening = "Underkänd vid lyssning" if rejected else "Inväntar lyssningsbedömning"
        review_html = f'<p><strong>{listening}</strong>{": " + escape(review["diagnosis"]) if rejected else ""}</p>'
        solo = review.get("melody_solo", {})
        if solo.get("status") in {"accepted", "unreviewed"}:
            solo_path = HERE / solo["audio"]
            if sha(solo_path) != solo["audio_sha256"] or sha(HERE / solo["program"]) != solo["program_sha256"]:
                raise ValueError(f"Accepted melody solo changed: {slug}")
            relative_solo = solo_path.relative_to(out).as_posix()
            solo_label = "Godkänd melodikanal ensam" if solo["status"] == "accepted" else "Ny melodikanal ensam – inväntar lyssning"
            review_html += f'<p><a href="{escape(relative_solo, quote=True)}">{solo_label}</a></p>'
        audio_relative = audio.relative_to(out).as_posix()
        program_relative = program.relative_to(out).as_posix()
        cards.append(f'''<article>
<h2>{escape(title(slug))}</h2>
{review_html}
<p>Källa {clock(start)}–{clock(end)} · {info.duration:.2f} s · {len(channels['sampled']) + len(channels['sid'])}/4 kanaler</p>
<audio controls preload="none" aria-label="{escape(title(slug), quote=True)}"><source src="{escape(audio_relative, quote=True)}" type="audio/wav"></audio>
<p class="mapping">Samplad kanal {sampled} · SID {sid} · Utelämnad: {omitted}</p>
<nav><a href="{escape(audio_relative, quote=True)}" download>WAV</a><a href="{escape(program_relative, quote=True)}" download>PRG</a><a href="{escape(slug, quote=True)}/audition.json">Mätningar</a></nav>
</article>''')
        markdown.append(f"| [{title(slug)}]({audio_relative}) | {clock(start)}–{clock(end)} | {kept} | {omitted} | {listening} |")
        identities[slug] = {"audio_sha256": sha(audio), "program_sha256": sha(program),
                            "duration_s": info.duration, "source_range_s": [start, end],
                            "source_channels": channels, "native_passed": True,
                            "listening_status": "rejected" if rejected else "unreviewed"}
    summary = {"status": "recorded_for_listening", "songs": len(identities),
               "source_channel_counts": dict(voice_counts), "profile": profile,
               "sample_values_verified": sample_count, "sid_writes_verified": synth_count,
               "underruns": 0, "accepted_references_unchanged": True,
               "listening_status": "Three previews rejected; Global Trash melody solo accepted. New Stardust/Desert solos and other previews await review. Digital correctness is separate from sound quality",
               "artifacts": identities}
    (out / "index-verification.json").write_text(json.dumps(summary, indent=2) + "\n")
    page = '''<!doctype html><html lang="sv"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>C64 · 20-sekundersprov</title>
<style>body{font:16px/1.5 system-ui,sans-serif;background:#f5f4ef;color:#20231f;margin:0}main{max-width:1120px;margin:auto;padding:32px 22px}h1{font-size:32px;margin-bottom:8px}header{max-width:820px;margin-bottom:28px}h2{font-size:19px;margin:0 0 5px}p{margin:5px 0 13px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:16px}article{background:white;border:1px solid #d7d9d0;border-radius:8px;padding:20px}article p{font-size:14px;color:#555d50}audio{width:100%;margin:6px 0 12px}nav{display:flex;gap:18px}a{color:#285c3d}footer{margin-top:30px;color:#555d50}</style>
<main><header><h1>C64 · 19 provlyssningar</h1>
<p>Cirka 20 sekunder per MOD. Åttabitars sampling genom SID-röst 3 och återanvända SID-ljudmallar, med samma spelare som den godkända Cream-versionen.</p>
<p>Alla filer är faktiska VICE-inspelningar med samma digiboost-profil. Kanalval, utelämnade stämmor och källavsnitt visas per låt. Klippen är lyssningskandidater; nya klanger är inte godkända ännu.</p></header><section class="grid">'''
    page += "\n".join(cards)
    page += '''</section><footer>PAL · MOS8580 + digiboost · 7 819,43 samplingsvärden/s · 22 050-Hz mono WAV. Endast klockstyrd beskärning, DC-borttagning och konstant förstärkning. Ingen EQ eller hostmixning.</footer></main>
<script>document.querySelectorAll('audio').forEach(player=>player.addEventListener('play',()=>document.querySelectorAll('audio').forEach(other=>{if(other!==player)other.pause()})));</script></html>'''
    (out / "listen.html").write_text(page)
    (out / "README.md").write_text("# MOD-prov, cirka 20 sekunder\n\n"
        "Faktiska VICE-inspelningar för lyssningsbedömning. Den godkända SID-röstspelaren används; originalkanaler kan vara utelämnade.\n\n"
        "| Låt / WAV | Källavsnitt | Behållna kanaler | Utelämnade | Lyssning |\n| --- | --- | --- | --- | --- |\n"
        + "\n".join(markdown) + "\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/auditions-20s")
    args = parser.parse_args()
    result = write(args.out.resolve())
    print(json.dumps({key: value for key, value in result.items() if key != "artifacts"}))

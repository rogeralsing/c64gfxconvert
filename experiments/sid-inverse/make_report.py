"""Create a local listening report from measured experiment artifacts."""
from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.ndimage import uniform_filter1d

HERE = Path(__file__).resolve().parent
COLORS = ("#83c5ff", "#f7b267", "#cba6f7")


def plot(series: list[tuple[str, np.ndarray]], *, log: bool = False, xlabel: str = "Tid") -> str:
    width, height, margin = 700, 170, 24
    values = [np.asarray(value, dtype=float) for _, value in series]
    low = min(float(value.min()) for value in values)
    high = max(float(value.max()) for value in values)
    span = max(high - low, 1e-9)
    paths = []
    for index, (label, value) in enumerate(series):
        step = max(1, len(value) // 550)
        offsets = np.arange(0, len(value), step)
        x = margin + offsets / max(1, len(value) - 1) * (width - 2 * margin)
        y = height - margin - (value[offsets] - low) / span * (height - 2 * margin)
        points = " ".join(f"{a:.1f},{b:.1f}" for a, b in zip(x, y))
        paths.append(f'<polyline points="{points}" fill="none" stroke="{COLORS[index]}" stroke-width="1.5"/>')
    legends = " · ".join(f'<span style="color:{COLORS[index]}">{html.escape(label)}</span>' for index, (label, _) in enumerate(series))
    return f'<figure><svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(xlabel)}"><path d="M24 8V146H680" fill="none" stroke="#536072"/>{"".join(paths)}</svg><figcaption>{legends} · {html.escape(xlabel)}</figcaption></figure>'


def envelope(audio: np.ndarray, rate: int) -> np.ndarray:
    return np.sqrt(np.maximum(uniform_filter1d(audio * audio, round(rate * 0.004)), 0))[::44]


def audio(path: Path, label: str) -> str:
    relative = path.relative_to(HERE).as_posix()
    return f'<label class="audio">{html.escape(label)}<audio controls preload="none" src="{relative}"></audio></label>'


def main() -> None:
    sweep = json.loads((HERE / "results/fresh-sweep/summary.json").read_text())
    selection = json.loads((HERE / "results/finalists/selection.json").read_text())
    robustness = json.loads((HERE / "results/robustness/robustness.json").read_text())
    waveforms = json.loads((HERE / "results/waveform-checks/waveform-checks.json").read_text())
    layered = json.loads((HERE / "results/fresh-layered-snare/summary.json").read_text())
    filter_free = json.loads((HERE / "results/fresh-hybrid-checks/filter-free-guitar/results.json").read_text())
    sections, rows = [], []
    names = {"kick": "Akustisk bastrumma", "snare": "Virvel", "guitar": "Nylonsträngad gitarr"}
    for kind in ("kick", "snare", "guitar"):
        selected = selection["kinds"][kind]
        winner = selected["winner"]
        directory = HERE / "results/finalists" / kind
        target, rate = sf.read(directory / "target.wav")
        best, _ = sf.read(directory / "best.wav")
        vice_path = HERE / "results" / f"vice-{kind}"
        vice_audio, vice_rate = sf.read(vice_path / "vice-instrument.wav")
        if vice_rate != rate or len(vice_audio) != len(best):
            raise ValueError(f"VICE instrument window differs in rate or length for {kind}")
        vice_audio -= vice_audio.mean()
        vice_peak = np.max(np.abs(vice_audio))
        if vice_peak < 1e-6:
            raise ValueError(f"VICE instrument window is silent for {kind}")
        sf.write(vice_path / "vice-listening.wav", vice_audio * 0.8 / vice_peak, rate, subtype="PCM_16")
        runs = [run for run in sweep["runs"] if run["kind"] == kind]
        values = {}
        for method, loss in (("cmaes", "spectral"), ("random", "spectral"), ("cmaes", "mse")):
            scores = [run["best_scores"]["spectral"] for run in runs if run["search_mode"] == method and run["loss_mode"] == loss]
            values[(method, loss)] = float(np.median(scores))
        rows.append(f'<tr><th>{names[kind]}</th><td>{values[("cmaes", "spectral")]:.3f}</td><td>{values[("random", "spectral")]:.3f}</td><td>{values[("cmaes", "mse")]:.3f}</td><td>{winner["spectral_mean"]:.3f} ± {winner["spectral_std"]:.5f}</td></tr>')
        comparisons = []
        for method, loss, label in (("cmaes", "spectral", "Evolution, spektralt mål"), ("random", "spectral", "Slumpsökning"), ("cmaes", "mse", "Evolution, vågformsfel")):
            matching = [run for run in runs if run["search_mode"] == method and run["loss_mode"] == loss]
            chosen = min(matching, key=lambda run: run["best_scores"]["spectral"])
            comparisons.append(audio(Path(chosen["output"]) / "best.wav", label))
        first = Path(runs[0]["output"])
        progress = []
        for method, label in (("cmaes", "Evolution"), ("random", "Slumpsökning")):
            histories = []
            for run in runs:
                if run["search_mode"] == method and run["loss_mode"] == "spectral":
                    receipt = json.loads((Path(run["output"]) / "results.json").read_text())
                    histories.append([entry["best_objective"] for entry in receipt["history"]])
            progress.append((label, np.median(histories, axis=0)))
        combined = np.concatenate([target, np.zeros(round(rate * 0.25)), best,
                                   np.zeros(round(rate * 0.4)), target,
                                   np.zeros(round(rate * 0.25)), best])
        sf.write(directory / "ab.wav", combined, rate, subtype="PCM_16")
        info = json.loads((directory / "results.json").read_text())
        sections.append(f'''<section>
<div class="section-top"><h2>{names[kind]}</h2><span>{info['register_writes']} registerskrivningar · en SID-röst</span></div>
<div class="players">{audio(directory / 'target.wav', 'Originalinspelning')}{audio(first / 'initial.wav', 'Första kandidaten')}{audio(directory / 'best.wav', 'Vald SID-kandidat')}{audio(vice_path / 'vice-listening.wav', 'C64-program i VICE')}{audio(directory / 'ab.wav', 'A/B: original, SID, original, SID')}</div>
{plot([('Original', envelope(target, rate)), ('SID', envelope(best, rate))], xlabel='RMS-envelope över 0,8 s; båda ljuden har normaliserats till samma toppnivå')}
<details><summary>Jämför sökmetoder och förlopp</summary><div class="players">{''.join(comparisons)}</div>{plot(progress, xlabel='Median av tre frön; bästa spektralfel efter varje utvärdering, lägre är bättre')}</details>
<details><summary>PCM som formatjämförelse</summary><p>Ideala jämna amplitudnivåer vid 8 kHz, utan verklig SID-DAC eller C64-spelare. Detta är en jämförelse av informationsförlust.</p><div class="players">{audio(HERE / 'results/pcm-reference' / kind / 'pcm4-8khz.wav', '4 bitar, 8 kHz')}{audio(HERE / 'results/pcm-reference' / kind / 'pcm8-8khz.wav', '8 bitar, 8 kHz')}</div></details>
<details><summary>Instrumentparametrar</summary><pre>{html.escape(json.dumps(winner['patch'], indent=2))}</pre></details>
</section>''')
    holdout = HERE / "results/robustness/guitar-holdout"
    waveform_rows = []
    for name, condition in waveforms["conditions"].items():
        waveform_rows.append(f'<tr><th>{html.escape(condition["waveform"])}</th><td>{condition["model"]}</td><td>{condition["spectral_mean"]:.3f} ± {condition["spectral_std_population"]:.5f}</td><td>{condition["normalization_gain_mean"]:.1f}×</td><td>{audio(HERE / "results/waveform-checks" / condition["listening_audio"], "Lyssna")}</td></tr>')
    checks = json.loads((HERE / "results/search-checks.json").read_text())
    body = f'''<!doctype html><html lang="sv"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SID-labb: ljudmatchning genom evolution</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#111820;color:#e8edf3;font:16px/1.6 system-ui,sans-serif}}main{{max-width:1100px;margin:auto;padding:48px 24px 80px}}h1{{font-size:clamp(30px,5vw,52px);line-height:1.1;max-width:850px;margin:10px 0 24px}}h2{{font-size:25px;margin:0}}p{{max-width:850px;color:#c5cdd7}}a{{color:#83c5ff}}.eyebrow{{color:#f7b267;font-size:13px;letter-spacing:.13em;text-transform:uppercase}}section{{border-top:1px solid #3c4755;padding:28px 0;margin-top:30px}}.section-top{{display:flex;justify-content:space-between;align-items:baseline;gap:16px;flex-wrap:wrap}}.section-top span,figcaption{{font-size:13px;color:#a9b6c7}}.players{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;margin:24px 0}}.audio{{display:grid;gap:8px;font-size:14px}}audio{{width:100%;height:40px}}table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #3c4755}}.table{{overflow-x:auto}}th{{font-weight:500}}thead{{color:#a9b6c7}}figure{{margin:18px 0}}svg{{display:block;width:100%;max-height:190px;background:#17222e}}details{{margin:18px 0}}summary{{cursor:pointer;color:#83c5ff}}pre{{overflow:auto;background:#17222e;padding:16px;font-size:13px}}.note{{border-left:3px solid #f7b267;padding-left:18px}}code{{font-size:.92em}}footer{{margin-top:40px;font-size:14px;color:#a9b6c7}}
</style><main>
<div class="eyebrow">C64 · experiment 2026-11-10</div><h1>Kan en SID-sekvens efterlikna ett inspelat instrument?</h1>
<p>Tre riktiga inspelningar jämförs med en röst i SID-emulatorn. Kandidaterna består av vågform, ADSR, pitchkurva, pulsbredd och ett eventuellt filtersvep. Inga PCM-samplingar lagras i de framtagna instrumenten.</p>
<p>Varje metod får 600 ljudrenderingar per instrument och slumpfrö. Tre frön och tre metoder ger 27 körningar, totalt 16 200 kandidater. Finalisterna mäts fem gånger. Lyssningsfilerna har samma toppnivå; det betyder inte samma upplevda ljudstyrka. Styrkurvor uppdateras vid 200 Hz, med extra exakta tidpunkter för gate- och brusövergångar.</p>
<div class="table"><table><thead><tr><th>Referens</th><th>Evolution, spektralt mål</th><th>Slumpsökning</th><th>Evolution, MSE</th><th>Vald finalist, medel ± spridning</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p class="note">Tabellen visar medianen av tre körningars spektralfel. Lägre är bättre enligt den valda mätfunktionen. Poängen är inte ett mått på mänsklig igenkänning. A/B-lyssning behövs för att bedöma klangen.</p>
{''.join(sections)}
<section><h2>En annan gitarrton, utan ny optimering</h2><p>Samma instrumentpatch spelas vid en annan grundton. Referensen är en separat C4-inspelning; träningen använde A3. Spektralfel: {robustness['guitar_holdout']['scores']['spectral']:.3f}.</p><div class="players">{audio(holdout / 'target.wav', 'Oberoende C4-inspelning')}{audio(holdout / 'same-patch-transposed.wav', 'Samma SID-patch vid C4')}</div></section>
<section><h2>Fler möjligheter i ljudchippet</h2><p>Två-röststestet blandar brus och triangel samtidigt för virveln. Det kostar två SID-röster och det gemensamma filtret. En separat sökning provar gitarr utan filter, så att filtret kan användas av andra instrument. Dessa är enskilda utforskande frön, inte en fullständig metodjämförelse.</p><p>Två-röstsvirvelns spektralfel efter fem omrenderingar: CMA-ES {layered['runs']['cmaes']['repeat_mean_spectral']:.3f}, random {layered['runs']['random']['repeat_mean_spectral']:.3f}. Filterfri gitarr: {filter_free['best_scores']['spectral']:.3f} vid sökningens valda rendering.</p><div class="players">{audio(HERE / 'results/finalists/snare/target.wav', 'Originalvirvel')}{audio(HERE / 'results/fresh-layered-snare/cmaes/best.wav', 'Två röster, CMA-ES')}{audio(HERE / 'results/fresh-hybrid-checks/filter-free-guitar/best.wav', 'Gitarr utan filter')}</div><details><summary>Kombinerade vågformer på 6581 och 8580</summary><p>Samma färdiga gitarrpatch spelas med ändrade vågformsbitar. Varje villkor mäts fem gånger. Patchen har inte optimerats om för varje vågform eller chipmodell. Stor förstärkning kan lyfta ett svagt ljud; den faktiska amplituden finns i kvittot.</p><div class="table"><table><thead><tr><th>Vågform</th><th>Chip</th><th>Spektralfel</th><th>Normaliseringsförstärkning</th><th>Ljud</th></tr></thead><tbody>{''.join(waveform_rows)}</tbody></table></div></details></section>
<section><h2>Vad kontrolleras?</h2><p>Separata kvitton innehåller upprepade renderingar, andra styrfrekvenser, båda SID-modellerna och återtriggning efter tidigare ljud. Ett separat VICE-prov kör registersekvensen som ett riktigt C64-program och jämför alla skrivningar och tidpunkter.</p><p><a href="results/robustness/robustness.json">Robusthet</a> · <a href="results/finalists/selection.json">Upprepade finalistmätningar</a> · <a href="results/fresh-sweep/summary.json">Alla slutliga sökkörningar</a> · <a href="results/search-checks.json">Oberoende mätkontroller</a> · <a href="assets/manifest.json">Referensljud och ursprung</a></p><p class="note">Första försöket återanvände en SID-instans efter reset. Reset lämnade intern status kvar, vilket kunde belöna en kandidat för föregående ljud. Slutjämförelsen använder en ny SID-instans per kandidat. De första resultaten är bevarade separat och används inte i tabellen.</p></section>
<footer>Referensljuden är CC0. Emulatorns analoga modell och det gemensamma SID-filtret begränsar överföringen till ett verkligt musikarrangemang. Den genererade C64-spelaren blankar skärmen och använder vänteloopar; samtidig grafik är inte verifierad.</footer></main></html>'''
    (HERE / "listen.html").write_text(body)
    print(HERE / "listen.html")


if __name__ == "__main__":
    main()

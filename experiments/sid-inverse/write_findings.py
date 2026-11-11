"""Write the Swedish findings report only after every final input is complete.

This reads measured artifacts; it performs no rendering, fitting, or playback.
The discarded cached-reset search is never a source for method comparisons.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo


HERE = Path(__file__).resolve().parent
KINDS = ("kick", "snare", "guitar")
NAMES = {"kick": "Akustisk bastrumma", "snare": "Virvel", "guitar": "Nylonsträngad gitarr"}
METHODS = (("cmaes", "spectral"), ("random", "spectral"), ("cmaes", "mse"))
METHOD_NAMES = {("cmaes", "spectral"): "CMA-ES, spektralt mål",
                ("random", "spectral"): "Slumpsökning, spektralt mål",
                ("cmaes", "mse"): "CMA-ES, MSE-mål"}
INPUTS = {
    "plan": "results/fresh-sweep/plan.json",
    "matrix": "results/fresh-sweep/summary.json",
    "selection": "results/finalists/selection.json",
    "robustness": "results/robustness/robustness.json",
    "layered": "results/fresh-layered-snare/summary.json",
    "filter_free": "results/fresh-hybrid-checks/filter-free-guitar/results.json",
    "waveforms": "results/waveform-checks/waveform-checks.json",
    "reset": "results/reset-diagnosis/diagnosis.json",
    "controls": "results/search-checks.json",
    "vice_kick": "results/vice-kick/receipt.json",
    "vice_snare": "results/vice-snare/receipt.json",
    "vice_guitar": "results/vice-guitar/receipt.json",
    "pcm": "results/pcm-reference/receipt.json",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def number(value: float, digits: int = 4) -> str:
    value = float(value)
    require(math.isfinite(value), "Rapporten kräver ändliga mätvärden")
    return f"{value:.{digits}f}".replace(".", ",")


def integer(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def table(headers: list[str], rows: list[list]) -> str:
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows),
    ])


def linked(key: str, label: str) -> str:
    return f"[{label}]({INPUTS[key]})"


def read_inputs() -> dict:
    missing = [path for path in INPUTS.values() if not (HERE / path).is_file()]
    require(not missing, "Slutunderlag saknas; ingen rapport skrevs: " + ", ".join(missing))
    return {name: json.loads((HERE / path).read_text()) for name, path in INPUTS.items()}


def validate(data: dict) -> dict:
    plan, matrix = data["plan"], data["matrix"]
    require(matrix["complete"] == matrix["planned"] == len(plan["jobs"]) == 27
            and not matrix["failures"] and len(matrix["runs"]) == 27,
            "Den korrigerade huvudmatrisen måste ha 27 avslutade körningar utan fel")
    runs = {}
    for run in matrix["runs"]:
        key = (run["kind"], run["seed"], run["search_mode"], run["loss_mode"])
        require(key not in runs and run["evaluations"] == 600, "Fel körningsidentitet eller renderingsbudget")
        require("fresh-sweep" in Path(run["output"]).parts, "Äldre sökresultat får inte användas i slutjämförelsen")
        runs[key] = run
    expected = {(kind, seed, method, loss) for kind in KINDS for seed in (1, 2, 3) for method, loss in METHODS}
    require(set(runs) == expected, "Huvudmatrisen saknar någon metod, referens eller något slumpfrö")
    planned = {(job["kind"], job["seed"], job["search_mode"], job["loss_mode"]) for job in plan["jobs"]}
    require(planned == expected and all(job["budget"] == 600 for job in plan["jobs"]), "Plan och avslutade budgetar skiljer sig")
    require(data["reset"]["decision"]["applied"] is True, "Återställningsfelet måste vara rättat")
    require(data["controls"]["status"] == "pass" and not data["controls"]["failures"], "Mätkontrollerna är inte godkända")
    require(plan["source_sha256"]["sid_render.py"] == data["controls"]["source_sha256"]["sid_render.py"],
            "Huvudmatris och mätkontroller använder olika renderarkällor")
    require(set(data["selection"]["kinds"]) == set(KINDS) and data["selection"]["repeats"] == 5,
            "Slutligt urval saknas eller använder annan upprepningsbudget")
    for kind in KINDS:
        group = data["selection"]["kinds"][kind]
        require(bool(group["candidates"]), f"Inga finalister för {kind}")
        require(all(len(candidate["repeat_scores"]) == 5 for candidate in group["candidates"]), "Finalistmätningar är ofullständiga")
        require(all("fresh-sweep" in Path(candidate["run"]).parts for candidate in group["candidates"]),
                "Finalistpoolen innehåller äldre sökresultat")
        require(abs(group["winner"]["spectral_mean"] - min(c["spectral_mean"] for c in group["candidates"])) < 1e-10,
                "Vald finalist har inte lägst upprepat medelfel")
        robust = data["robustness"]["kinds"][kind]
        require(len(robust["repeatability"]["scores"]) == 10 and set(robust["histories"]) == {"same", "different"},
                "Robusthetsmätningarna är ofullständiga")
        require(set(robust["control_rates"]) == {"50", "100", "200", "400"} and set(robust["models"]) == {"6581", "8580"},
                "Styrtakter eller chipmodeller saknas")
        vice = data[f"vice_{kind}"]
        require(vice["trace"]["register_sequence_matches"] and vice["trace"]["max_timing_error_cycles"] == 0
                and vice["trace"]["timing_mismatches"] == 0 and vice["capture"]["instrument_window_frames"] > 0
                and vice["capture"]["instrument_window_peak"] > 0.001,
                f"VICE-verifieringen för {kind} är inte komplett och exakt")
    holdout = data["robustness"]["guitar_holdout"]
    require(holdout["same_patch_as_training"] and holdout["no_retraining"] and holdout["reference_is_independent_recording"],
            "Gitarrens kontrollton måste vara oberoende och får inte optimeras om")
    layered = data["layered"]
    require(layered["same_render_budget_per_method"] == 600 and layered["shared_initial_programs_verified"] == 150,
            "Tvåröstsförsöket saknar lika budget eller gemensamma startprogram")
    for method in ("cmaes", "random"):
        run = layered["runs"][method]
        require(run["evaluations"] == run["budget"] == 600 and len(run["repeat_scores"]) == 5,
                "Tvåröstsförsöket är ofullständigt")
    free = data["filter_free"]
    require(free["budget"] == free["evaluations"] == 600 and free["best_patch"]["filter_mode"] == "off",
            "Filterfri gitarr saknar korrekt resultat")
    require(data["waveforms"]["no_retraining"] and data["waveforms"]["repeats_per_condition"] == 5
            and len(data["waveforms"]["conditions"]) == 14,
            "Vågformskontrollen måste omfatta sju vågformer på båda chipmodellerna")
    for kind in KINDS:
        require(set(data["pcm"]["kinds"][kind]) == {"4", "8"}, "PCM-formatjämförelsen är ofullständig")
    return runs


def report(data: dict, runs: dict) -> str:
    def scores(kind: str, method: str, loss: str, metric: str = "spectral") -> list[float]:
        return [runs[(kind, seed, method, loss)]["best_scores"][metric] for seed in (1, 2, 3)]

    selected = data["selection"]["kinds"]
    robust = data["robustness"]
    paired_wins = sum(runs[(kind, seed, "cmaes", "spectral")]["best_scores"]["spectral"]
                      < runs[(kind, seed, "random", "spectral")]["best_scores"]["spectral"]
                      for kind in KINDS for seed in (1, 2, 3))
    median_wins = sum(median(scores(kind, "cmaes", "spectral")) < median(scores(kind, "random", "spectral")) for kind in KINDS)
    sections = [
        "# SID-labb: matchning av inspelade instrument\n",
        "Experimentet producerar parametriserade SID-styrprogram från tre verkliga inspelningar: bastrumma, virvel och nylonsträngad gitarr. "
        "Programmen använder oscillatorer, ADSR och tidsstyrda registerändringar; de innehåller inga PCM-samplingar. "
        "Den korrigerade sökningen, upprepade mätningar och registersekvensernas C64-uppspelning har kontrollerats. "
        "Hur väl människor känner igen instrumenten är inte mätt; bedöm klangen med [lyssningssidan](listen.html).\n",
        f"Rapporten bygger på färdiga kvitton och genererades {datetime.now(ZoneInfo('Europe/Stockholm')).isoformat(timespec='seconds')}. "
        "Referensljuden är CC0; original, licenser och kontrollsummor finns i [källredovisningen](references.md) och [ljudmanifestet](assets/manifest.json).\n",
        "## Det första återställningsförsöket ska inte användas som slutjämförelse\n",
        "Den första renderaren återanvände en SID-instans efter reset. Den inbyggda återställningen lämnade oscillatorns fasackumulator, "
        "envelopens räknare och analog filterstatus kvar. Föregående kandidat kunde därför påverka nästa ljud. "
        "En längre inledande väntan var ingen allmän lösning. Slutkörningarna skapar i stället en ny native SID-instans per kandidat. "
        "Kontinuerliga notföljder använder avsiktligt samma instans genom hela följden. "
        "De äldre katalogerna `results/sweep` och `results/layered-snare` är bevarade som felsökningsevidens men används inte i metodtabellen.\n",
    ]
    conditions = data["reset"]["conditions"].values()
    cached = [item["spectral_std"] for item in conditions if item.get("case") == "layered" and item.get("mode") == "cached" and item.get("pre_roll_s") == 0.05]
    fresh = [item["spectral_std"] for item in conditions if item.get("case") == "layered" and item.get("mode") == "fresh" and item.get("pre_roll_s") == 0.05]
    require(bool(cached) and bool(fresh), "Återställningsdiagnosen saknar jämförbara villkor")
    sections.append(f"I diagnosens tvåröstsexempel låg standardavvikelsen mellan {number(min(cached), 6)} och {number(max(cached), 6)} med återanvänd instans, "
                    f"jämfört med {number(min(fresh), 6)}–{number(max(fresh), 6)} med nya instanser. "
                    "En liten variation från emulatormodellen finns kvar; bitidentiskt PCM-ljud utlovas inte. "
                    + linked("reset", "Återställningsdiagnos") + ".\n")
    sections += [
        "## Lika sökbudget: 600 kandidater per metod och slumpfrö\n",
        "Tre referenser, tre frön och tre metod/målfunktionskombinationer ger 27 körningar och 16 200 kandidatrenderingar. "
        "Varje körning inkluderar 150 gemensamma startprogram och får därefter använda återstående budget. "
        "CMA-ES jämförs med en full slumpsökning med samma totalbudget, inte enbart med startkvarten. "
        "Modellen är 6581, ljudfrekvensen 22 050 Hz och styrkurvornas takt 200 Hz. Gate- och brusövergångar får dessutom egna exakta cykeltidpunkter.\n",
        "Tabellen visar spektralfel även för MSE-tränade program, samt deras MSE. Lägre betyder bättre enligt respektive mätfunktion. "
        "Alla ljud DC-korrigeras och toppnormaliseras till 0,8 före jämförelsen. Detta jämför klang och relativ envelope, inte verklig SID-ljudstyrka eller upplevd loudness.\n",
    ]
    rows = []
    for kind in KINDS:
        for method, loss in METHODS:
            values = scores(kind, method, loss)
            rows.append([NAMES[kind], METHOD_NAMES[(method, loss)], " / ".join(number(v) for v in values),
                         number(median(values)), number(median(scores(kind, method, loss, "mse")), 6)])
    sections.append(table(["Referens", "Sökning och träningsmål", "Spektralfel: frö 1 / 2 / 3", "Median", "Median MSE"], rows) + "\n")
    sections.append(f"CMA-ES med spektralt mål fick lägre median än slumpsökningen för {median_wins} av 3 referenser och lägre fel i {paired_wins} av 9 matchade fröpar. "
                    "Det är observationer för dessa mål och denna budget, inte ett generellt bevis för att CMA-ES är överlägset. "
                    "Att välja eller granska ett MSE-tränat program med spektralfunktionen är en jämförelse på samma träningsljud, inte oberoende validering. "
                    + linked("matrix", "Alla korrigerade sökkörningar") + ".\n")
    sections += ["## Finalisturvalet är ett separat steg\n",
                 "De bästa programmen per körning samlas, identiska program slås ihop och varje finalist renderas fem gånger. "
                 "Urvalet använder medelvärdet av poängen; ljudvågorna medelvärdesbildas inte. Dessa renderingar tillkommer utöver sökbudgeten. "
                 "Poolen innehåller både CMA-mål och slumpsökning. Dess vinnare ska därför inte räknas som ännu en rättvis jämförelse mellan metoderna.\n"]
    rows = []
    validation_count = 0
    for kind in KINDS:
        group, winner = selected[kind], selected[kind]["winner"]
        validation_count += group["validation_evaluations"]
        filter_mode = winner["patch"]["filter_mode"]
        rows.append([NAMES[kind], len(group["candidates"]), METHOD_NAMES[(winner["search_mode"], winner["loss_mode"])] + f", frö {winner['seed']}",
                     f"{number(winner['spectral_mean'])} ± {number(winner['spectral_std'], 6)}",
                     data[f"vice_{kind}"]["register_writes"], "nej" if filter_mode == "off" else filter_mode])
    sections.append(table(["Referens", "Unika finalister", "Valt program", "Medelfel ± standardavvikelse", "Registerskrivningar", "Gemensamt filter"], rows) + "\n")
    sections.append(f"Finalistpoolerna krävde sammanlagt {integer(validation_count)} poängrenderingar. Varje valt huvudprogram använder en fysisk SID-röst. "
                    "Filterägarskap måste samordnas mellan instrument i ett arrangemang. " + linked("selection", "Finalistkvitto") + ".\n")
    sections += ["## Ny instans, kontinuerlig återtriggning och annan ton\n",
                 "Tio omrenderingar från ny instans mäter upprepning i en isolerad start. Därefter spelas samma patch efter en likadan respektive annan föregående not, "
                 "utan reset mellan noterna. Det senare provar instrumentets beroende av redan pågående SID-status.\n"]
    rows = []
    for kind in KINDS:
        result = robust["kinds"][kind]
        repeat = result["repeatability"]
        rows.append([NAMES[kind], f"{number(repeat['spectral_mean'])} ± {number(repeat['spectral_std_population'], 6)}",
                     number(result["histories"]["same"]["scores"]["spectral"]),
                     number(result["histories"]["different"]["scores"]["spectral"]),
                     number(result["models"]["8580"]["scores"]["spectral"])])
    sections.append(table(["Referens", "Ny instans: medel ± SD", "Efter samma not", "Efter annan not", "Återspel på 8580"], rows) + "\n")
    sections.append("En stabil isolerad start visar inte att varje återtriggning i en låt blir likadan. Modellbytet återspelar samma 6581-patch på 8580 utan ny optimering. "
                    "Historikfallen och modellbytena är enskilda återspel, medan startkolumnen bygger på tio mätningar.\n")
    rows = [[NAMES[kind], *(number(robust["kinds"][kind]["control_rates"][str(rate)]["scores"]["spectral"]) for rate in (50, 100, 200, 400))] for kind in KINDS]
    sections.append(table(["Styrkurvornas takt", "50 Hz", "100 Hz", "200 Hz", "400 Hz"], rows) + "\n")
    holdout = robust["guitar_holdout"]
    sections.append("Takterna ändras utan omoptimering och gäller vanliga parameterkurvor; gate- och brusövergångar ligger kvar på extra exakta cykler. "
                    "50 Hz i tabellen är därför inte bevis för en strikt spelare som bara arbetar en gång per bildruta. "
                    f"Gitarrpatchen återspelades också mot en separat C4-inspelning vid {number(holdout['holdout_root_hz'], 4)} Hz, "
                    f"efter träning vid {number(holdout['training_root_hz'], 4)} Hz. Felet blev {number(holdout['scores']['spectral'])}. "
                    "Samma patch användes utan ny träning. En sådan kontrollton räcker inte för att fastställa kvalitet över hela klaviaturen. "
                    + linked("robustness", "Robusthetskvitto") + ".\n")
    sections += ["## Mer uttryck: två röster, filterfri gitarr och kombinerade vågformer\n",
                 "Tvåröstsförsöket spelar filtrerat brus och en ofiltrerad triangelkropp samtidigt. Det använder två SID-röster och det gemensamma filtret. "
                 "Nedan visas de tre huvudgrenarnas virvelmedianer som bakgrund, följt av det separata tvåröstsförsöket.\n"]
    rows = [["En röst: " + METHOD_NAMES[(method, loss)], "3 frön", number(median(scores("snare", method, loss))), "1", "enligt vald patch"] for method, loss in METHODS]
    for method in ("cmaes", "random"):
        run = data["layered"]["runs"][method]
        rows.append(["Två röster: " + ("CMA-ES" if method == "cmaes" else "slumpsökning"), f"frö {run['seed']}",
                     f"{number(run['repeat_mean_spectral'])} ± {number(run['repeat_std_spectral'], 6)}", run["resources"]["sid_voices"], "ja, bara brusets röst"])
    sections.append(table(["Virvelexperiment", "Underlag", "Spektralfel", "SID-röster", "Filter"], rows) + "\n")
    sections.append("Tvåröstsförsöket har bara ett frö, ett annat parameterutrymme och en annan CMA-populationsstorlek. "
                    "Det bevisar inte att två röster matchar bättre; den bästa enröstsgrenen måste också räknas med. "
                    "De två nya sökningarna kostade 600 kandidater vardera plus fem kontrollrenderingar per vinnare. "
                    + linked("layered", "Tvåröstskvitto") + ".\n")
    free = data["filter_free"]
    standard = runs[("guitar", free["seed"], "cmaes", "spectral")]
    sections.append(f"Den filterfria gitarrsökningen använde en röst, frö {free['seed']} och 600 kandidater. Felet blev {number(free['best_scores']['spectral'])}, "
                    f"jämfört med {number(standard['best_scores']['spectral'])} i huvudgrenens motsvarande frö. "
                    "Den lämnar den gemensamma filterresursen ledig. Detta är en resursavvägning i en enskild sökning, inte ett trefröstest av vilket ljud som är bäst. "
                    + linked("filter_free", "Filterfri gitarr") + ".\n")
    waveforms = data["waveforms"]
    wave_rows = []
    for mask in (0x10, 0x20, 0x40, 0x30, 0x50, 0x60, 0x70):
        pair = [next(item for item in waveforms["conditions"].values() if item["model"] == model and item["mask"] == mask) for model in ("6581", "8580")]
        wave_rows.append([f"${mask:02x}: {pair[0]['waveform']}", *(number(item["spectral_mean"]) for item in pair),
                          " / ".join(number(item["normalization_gain_mean"], 2) for item in pair)])
    sections.append("Vågformskontrollen byter de verkliga SID-vågformsbitarna i samma inlärda gitarrprogram. Brusattacker och övriga styrningar behålls. "
                    "Varje villkor mäts fem gånger. Kombinerade SID-vågformer är chipbeteende, inte summor av vanliga oscillatorvågor; här optimeras inget om.\n")
    sections.append(table(["Vågform", "6581: medelfel", "8580: medelfel", "Normaliseringsgain 6581 / 8580"], wave_rows) + "\n")
    sections.append("Tabellen gäller denna enda patch. Den visar inte bästa möjliga resultat efter ny sökning för respektive vågform. "
                    "Normaliseringsgain redovisas eftersom ett svagt råljud kan låta mycket starkare i lyssningskopian. "
                    + linked("waveforms", "Vågformskvitto") + ".\n")
    sections += ["## Verkligt C64-program i VICE\n",
                 "De tre valda huvudprogrammen exporteras som PAL-PRG och körs i VICE. Registersekvensen och varje relativ cykeltid jämförs med den direkta renderaren; "
                 "endast en gemensam startförskjutning tillåts. Separat ljudfångst bekräftar att programmen också ger PCM-ljud. "
                 "Ljudfönstret förankras i registerdumpens klocka och den kända förberedelsen; korrelationssökningen får bara röra sig ±20 ms runt detta ankare. "
                 "En obegränsad sökning kunde annars välja VICE:s uppstarts- eller initieringsklick. Spelaren håller slutstatus ytterligare 20 ms så att hela instrumentfönstret hinner skrivas till WAV.\n"]
    rows = []
    for kind in KINDS:
        receipt = data[f"vice_{kind}"]
        rows.append([NAMES[kind], receipt["program_bytes"], receipt["register_writes"], receipt["trace"]["max_timing_error_cycles"],
                     number(receipt["audio"]["waveform_correlation"]), number(receipt["audio"]["gain_aligned_normalized_rmse"]),
                     number(receipt["direct_store_cycle_lower_bound_percent"], 4) + "%"])
    sections.append(table(["Program", "PRG-byte", "Patchskrivningar", "Största cykelfel", "Ljudkorrelation", "Gainjusterat NRMSE", "Store-only nedre gräns"], rows) + "\n")
    sections.append("Ljudjämförelsen tillåter en gemensam tidsförskjutning och linjär gain mellan olika emulatorkärnor; den är inte ett bitlikhetsprov. "
                    "Spelaren blankar skärmen, stänger av avbrott och använder vänteloopar. Store-only-kolumnen räknar bara sex cykler per skrivning, inte parser, IRQ eller grafik. "
                    "Samtidig grafik, en delad musikspelare och riktiga SID-chip är inte verifierade. "
                    + " · ".join(linked(f"vice_{kind}", f"VICE: {NAMES[kind].lower()}") for kind in KINDS) + ".\n")
    sections += ["## PCM som formatreferens\n",
                 "Det separata PCM-provet kvantiserar till jämna ideala amplitudnivåer vid 8 kHz och återger med zero-order hold. "
                 "Det modellerar varken SID-DAC:ens olinjäritet, huvudvolymens påverkan på andra röster eller en C64-spelares CPU-kostnad.\n"]
    rows = []
    for kind in KINDS:
        pair = data["pcm"]["kinds"][kind]
        rows.append([NAMES[kind], number(pair["4"]["scores"]["spectral"]), pair["4"]["packed_bytes"],
                     number(pair["8"]["scores"]["spectral"]), pair["8"]["packed_bytes"]])
    sections.append(table(["Referens", "4 bit: fel", "4 bit: packade byte", "8 bit: fel", "8 bit: packade byte"], rows) + "\n")
    sections.append("Det är en jämförelse av informationsförlust, inte ett löfte om samma resultat från $D418 eller Mahoney-utmatning på hårdvara. "
                    + linked("pcm", "PCM-kvitto") + ".\n")
    controls = data["controls"]
    recovery = controls["synthetic_recovery"]
    inverted = controls["metric_controls"]["scores"]["polarity_inverted"]
    sections += ["## Vad fungerar, och vad ska lämnas utanför slutsatsen?\n",
                 f"Mätkontrollerna har status `{controls['status']}`. En polaritetsvänd ton fick spektralfel {number(inverted['spectral'], 6)} "
                 f"men PCM-MSE {number(inverted['mse'], 6)}, vilket visar varför målfunktionerna kan föredra olika program. "
                 f"Den syntetiska återhämtningskontrollen gick från {number(recovery['initial_scores']['spectral'])} till {number(recovery['best_scores']['spectral'])} "
                 f"på {recovery['evaluation_count']} kandidater. Samma SID-renderare skapade det målet, så kontrollen visar sökloopens funktion, inte akustisk imitation eller emulatormodellens riktighet. "
                 + linked("controls", "Mätkontroller") + ".\n",
                 "Behåll den reproducerbara sökloopen, fulla slumpbudgetar, flera frön, råa ljudfiler, upprepade poängmätningar och de verifierade registerprogrammen. "
                 "Använd den oberoende gitarrtonen och kontinuerliga notföljder när en patch ska bli ett återanvändbart instrument. "
                 "Välj en filterfri patch eller PCM först efter att ljud och gemensamma hårdvaruresurser vägts mot varandra.\n",
                 "Använd inte resultaten från återanvänd/resetad instans som slutlig metodjämförelse. "
                 "Tolka inte ett lågt spektralfel som mänskligt godkänd klang, ett urval ur den sammanslagna finalistpoolen som rättvis metodtävling eller ett enstaka tvåröstsförsök som bevis för fler rösters nytta. "
                 "En isolerad ny SID-instans är inte ett bevis för problemfri återtriggning, och exakt VICE-registertiming är inte ett bevis för fysisk SID-likhet.\n",
                 "## Reproduktion och underlag\n",
                 "[Lyssningssidan](listen.html) innehåller A/B-ljud. [Källor och licenser](references.md) beskriver inspelningarna. "
                 "[Körningsplanen](results/fresh-sweep/plan.json) innehåller frön, budgetar, källkodshashar och paketversioner. "
                 "Slutlig artefaktkontroll utförs separat av [verify_lab.py](verify_lab.py); denna rapportgenerator ersätter inte den kontrollen.\n",
                 "Rapporten använder renderarkällan med SHA-256 `" + data["plan"]["source_sha256"]["sid_render.py"] + "`.\n",
                 "```sh\nrtk proxy experiments/sid-inverse/.venv/bin/python experiments/sid-inverse/write_findings.py\n```\n",
    ]
    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "REPORT.md")
    args = parser.parse_args()
    try:
        data = read_inputs()
        runs = validate(data)
        text = report(data, runs)
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise SystemExit(f"Rapporten skapades inte: {error}") from error
    args.output.write_text(text)
    print(args.output.resolve())


if __name__ == "__main__":
    main()

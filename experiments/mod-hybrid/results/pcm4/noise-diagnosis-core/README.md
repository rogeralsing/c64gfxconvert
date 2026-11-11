Brusdiagnos av den ursprungliga fyrkanalsmixen
============================================

Provet använder exakt samma192431 D418-värden från den verkliga VICE-körningens första50 sekunder. `actual-timing.wav` återger uppmätta cykeltider; `uniform-timing.wav` återger samma värden med exakt256 cykler mellan skrivningarna. Båda använder samma VICE3.10 reSID-kärna, modell6581, filterbias500mV och oförändrad förstärkning. Program-, registerspårs- och bibliotekshashar finns i `result.json`.

Återspelningen med de verkliga tidpunkterna överensstämmer med den inspelade VICE-vågformen till korrelation1,000000. Mot den jämna klockan är korrelationen0,99367 och skillnadens RMS0,002456, cirka19dB under signalen. Fasklockans medelavvikelse är7,56 cykler och standardavvikelsen23,97 cykler, ungefär24 mikrosekunder. Ett separat prov med8 cyklers konstant förskjutning ändrar inte slutsatsen.

Bandnivåerna kvarstår praktiskt taget när tidsvariationerna tas bort. För1,0–1,924kHz är RMS0,005927 i båda fallen; för1,924–4kHz är nivåerna0,004069 respektive0,004072. Tidsvariationerna bidrar alltså med ett mindre fel, men är inte huvudförklaringen till det kraftiga bruset. Detta prov ändrar inga samplingsvärden och isolerar därför inte själva kvantiseringsfelet; den separata kvantiseringsdiagnosen ska användas för jämförelsen med eller utan residualåterkoppling.

`actual-preview.wav` och `uniform-preview.wav` är samma30–50-sekunders utsnitt med gemensam förstärkning5,7405. Ingen profil har normaliserats separat. `jitter-difference.wav` är skillnaden mot provet med konstant faskompensation. Mätningarna exkluderar start och slut och avser1–49 sekunder.

SID:ens programmerbara filter kan inte lågpassfiltrera D418-stegen. Det syns i den bevarade officiella källan `results/channel-fit-2/resid-core/vice-3.10/src/resid/filter8580new.h`: `Filter::output()` summerar först de valda filterutgångarna och rösterna och tillämpar därefter `f.gain[vol][idx2]` på rad1499. `writeMODE_VOL()` i motsvarande `.cc` lagrar volymens nedre fyra bitar separat. Volymändringen sker efter filtret. Den externa RC-modellen ligger efter detta steg men dess lågpassgräns är omkring16kHz, vilket inte undertrycker bilderna från3,85kHz-sampling tillräckligt. Källa: [officiellt VICE3.10-arkiv](https://downloads.sourceforge.net/project/vice-emu/releases/vice-3.10.tar.gz), verifierat mot installerad Homebrew-formel.

Återskapa med `experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/results/pcm4/noise-diagnosis-core/probe.py`. Originalets ljud, program och registerspår har bevarats. Den nya nearest-versionen byggs i en separat katalog. En återbyggnad med gammal indata utan mode blev byte för byte identisk med det gamla programmet; underlaget finns i `legacy-rebuild/`.

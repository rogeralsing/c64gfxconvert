# SID-labb: matchning av inspelade instrument

Experimentet producerar parametriserade SID-styrprogram från tre verkliga inspelningar: bastrumma, virvel och nylonsträngad gitarr. Programmen använder oscillatorer, ADSR och tidsstyrda registerändringar; de innehåller inga PCM-samplingar. Den korrigerade sökningen, upprepade mätningar och registersekvensernas C64-uppspelning har kontrollerats. Hur väl människor känner igen instrumenten är inte mätt; bedöm klangen med [lyssningssidan](listen.html).

Rapporten bygger på färdiga kvitton och genererades 2026-11-10T11:35:15+01:00. Referensljuden är CC0; original, licenser och kontrollsummor finns i [källredovisningen](references.md) och [ljudmanifestet](assets/manifest.json).

## Det första återställningsförsöket ska inte användas som slutjämförelse

Den första renderaren återanvände en SID-instans efter reset. Den inbyggda återställningen lämnade oscillatorns fasackumulator, envelopens räknare och analog filterstatus kvar. Föregående kandidat kunde därför påverka nästa ljud. En längre inledande väntan var ingen allmän lösning. Slutkörningarna skapar i stället en ny native SID-instans per kandidat. Kontinuerliga notföljder använder avsiktligt samma instans genom hela följden. De äldre katalogerna `results/sweep` och `results/layered-snare` är bevarade som felsökningsevidens men används inte i metodtabellen.

I diagnosens tvåröstsexempel låg standardavvikelsen mellan 0,054943 och 0,070009 med återanvänd instans, jämfört med 0,000125–0,000218 med nya instanser. En liten variation från emulatormodellen finns kvar; bitidentiskt PCM-ljud utlovas inte. [Återställningsdiagnos](results/reset-diagnosis/diagnosis.json).

## Lika sökbudget: 600 kandidater per metod och slumpfrö

Tre referenser, tre frön och tre metod/målfunktionskombinationer ger 27 körningar och 16 200 kandidatrenderingar. Varje körning inkluderar 150 gemensamma startprogram och får därefter använda återstående budget. CMA-ES jämförs med en full slumpsökning med samma totalbudget, inte enbart med startkvarten. Modellen är 6581, ljudfrekvensen 22 050 Hz och styrkurvornas takt 200 Hz. Gate- och brusövergångar får dessutom egna exakta cykeltidpunkter.

Tabellen visar spektralfel även för MSE-tränade program, samt deras MSE. Lägre betyder bättre enligt respektive mätfunktion. Alla ljud DC-korrigeras och toppnormaliseras till 0,8 före jämförelsen. Detta jämför klang och relativ envelope, inte verklig SID-ljudstyrka eller upplevd loudness.

| Referens | Sökning och träningsmål | Spektralfel: frö 1 / 2 / 3 | Median | Median MSE |
| --- | --- | --- | --- | --- |
| Akustisk bastrumma | CMA-ES, spektralt mål | 0,7596 / 0,7607 / 0,7693 | 0,7607 | 0,016819 |
| Akustisk bastrumma | Slumpsökning, spektralt mål | 0,7917 / 0,7450 / 0,7779 | 0,7779 | 0,013827 |
| Akustisk bastrumma | CMA-ES, MSE-mål | 0,8492 / 0,7996 / 0,7798 | 0,7996 | 0,009861 |
| Virvel | CMA-ES, spektralt mål | 1,5833 / 1,5041 / 1,4761 | 1,5041 | 0,014469 |
| Virvel | Slumpsökning, spektralt mål | 1,5399 / 1,5613 / 1,5895 | 1,5613 | 0,015736 |
| Virvel | CMA-ES, MSE-mål | 1,4203 / 1,6051 / 1,5058 | 1,5058 | 0,013378 |
| Nylonsträngad gitarr | CMA-ES, spektralt mål | 0,6646 / 0,6396 / 0,6515 | 0,6515 | 0,063055 |
| Nylonsträngad gitarr | Slumpsökning, spektralt mål | 0,6880 / 0,6850 / 0,6514 | 0,6850 | 0,035951 |
| Nylonsträngad gitarr | CMA-ES, MSE-mål | 0,6526 / 0,7282 / 0,7543 | 0,7282 | 0,018552 |

CMA-ES med spektralt mål fick lägre median än slumpsökningen för 3 av 3 referenser och lägre fel i 6 av 9 matchade fröpar. Det är observationer för dessa mål och denna budget, inte ett generellt bevis för att CMA-ES är överlägset. Att välja eller granska ett MSE-tränat program med spektralfunktionen är en jämförelse på samma träningsljud, inte oberoende validering. [Alla korrigerade sökkörningar](results/fresh-sweep/summary.json).

## Finalisturvalet är ett separat steg

De bästa programmen per körning samlas, identiska program slås ihop och varje finalist renderas fem gånger. Urvalet använder medelvärdet av poängen; ljudvågorna medelvärdesbildas inte. Dessa renderingar tillkommer utöver sökbudgeten. Poolen innehåller både CMA-mål och slumpsökning. Dess vinnare ska därför inte räknas som ännu en rättvis jämförelse mellan metoderna.

| Referens | Unika finalister | Valt program | Medelfel ± standardavvikelse | Registerskrivningar | Gemensamt filter |
| --- | --- | --- | --- | --- | --- |
| Akustisk bastrumma | 53 | Slumpsökning, spektralt mål, frö 2 | 0,7448 ± 0,000105 | 157 | nej |
| Virvel | 54 | CMA-ES, MSE-mål, frö 1 | 1,4203 ± 0,000648 | 214 | bandpass |
| Nylonsträngad gitarr | 50 | CMA-ES, spektralt mål, frö 2 | 0,6394 ± 0,000049 | 152 | nej |

Finalistpoolerna krävde sammanlagt 785 poängrenderingar. Varje valt huvudprogram använder en fysisk SID-röst. Filterägarskap måste samordnas mellan instrument i ett arrangemang. [Finalistkvitto](results/finalists/selection.json).

## Ny instans, kontinuerlig återtriggning och annan ton

Tio omrenderingar från ny instans mäter upprepning i en isolerad start. Därefter spelas samma patch efter en likadan respektive annan föregående not, utan reset mellan noterna. Det senare provar instrumentets beroende av redan pågående SID-status.

| Referens | Ny instans: medel ± SD | Efter samma not | Efter annan not | Återspel på 8580 |
| --- | --- | --- | --- | --- |
| Akustisk bastrumma | 0,7453 ± 0,000107 | 0,6815 | 1,2208 | 1,9305 |
| Virvel | 1,4205 ± 0,000642 | 0,8604 | 2,7703 | 1,7454 |
| Nylonsträngad gitarr | 0,6393 ± 0,000028 | 0,6297 | 0,6296 | 0,9232 |

En stabil isolerad start visar inte att varje återtriggning i en låt blir likadan. Modellbytet återspelar samma 6581-patch på 8580 utan ny optimering. Historikfallen och modellbytena är enskilda återspel, medan startkolumnen bygger på tio mätningar.

| Styrkurvornas takt | 50 Hz | 100 Hz | 200 Hz | 400 Hz |
| --- | --- | --- | --- | --- |
| Akustisk bastrumma | 0,8603 | 0,7529 | 0,7453 | 0,7483 |
| Virvel | 1,4758 | 1,4934 | 1,4200 | 1,4083 |
| Nylonsträngad gitarr | 0,6419 | 0,6394 | 0,6392 | 0,6395 |

Takterna ändras utan omoptimering och gäller vanliga parameterkurvor; gate- och brusövergångar ligger kvar på extra exakta cykler. 50 Hz i tabellen är därför inte bevis för en strikt spelare som bara arbetar en gång per bildruta. Gitarrpatchen återspelades också mot en separat C4-inspelning vid 262,9694 Hz, efter träning vid 221,4764 Hz. Felet blev 0,6731. Samma patch användes utan ny träning. En sådan kontrollton räcker inte för att fastställa kvalitet över hela klaviaturen. [Robusthetskvitto](results/robustness/robustness.json).

## Mer uttryck: två röster, filterfri gitarr och kombinerade vågformer

Tvåröstsförsöket spelar filtrerat brus och en ofiltrerad triangelkropp samtidigt. Det använder två SID-röster och det gemensamma filtret. Nedan visas de tre huvudgrenarnas virvelmedianer som bakgrund, följt av det separata tvåröstsförsöket.

| Virvelexperiment | Underlag | Spektralfel | SID-röster | Filter |
| --- | --- | --- | --- | --- |
| En röst: CMA-ES, spektralt mål | 3 frön | 1,5041 | 1 | enligt vald patch |
| En röst: Slumpsökning, spektralt mål | 3 frön | 1,5613 | 1 | enligt vald patch |
| En röst: CMA-ES, MSE-mål | 3 frön | 1,5058 | 1 | enligt vald patch |
| Två röster: CMA-ES | frö 1 | 1,4706 ± 0,000150 | 2 | ja, bara brusets röst |
| Två röster: slumpsökning | frö 1 | 1,5006 ± 0,000976 | 2 | ja, bara brusets röst |

Tvåröstsförsöket har bara ett frö, ett annat parameterutrymme och en annan CMA-populationsstorlek. Det bevisar inte att två röster matchar bättre; den bästa enröstsgrenen måste också räknas med. De två nya sökningarna kostade 600 kandidater vardera plus fem kontrollrenderingar per vinnare. [Tvåröstskvitto](results/fresh-layered-snare/summary.json).

Den filterfria gitarrsökningen använde en röst, frö 1 och 600 kandidater. Felet blev 0,6547, jämfört med 0,6646 i huvudgrenens motsvarande frö. Den lämnar den gemensamma filterresursen ledig. Detta är en resursavvägning i en enskild sökning, inte ett trefröstest av vilket ljud som är bäst. [Filterfri gitarr](results/fresh-hybrid-checks/filter-free-guitar/results.json).

Vågformskontrollen byter de verkliga SID-vågformsbitarna i samma inlärda gitarrprogram. Brusattacker och övriga styrningar behålls. Varje villkor mäts fem gånger. Kombinerade SID-vågformer är chipbeteende, inte summor av vanliga oscillatorvågor; här optimeras inget om.

| Vågform | 6581: medelfel | 8580: medelfel | Normaliseringsgain 6581 / 8580 |
| --- | --- | --- | --- |
| $10: triangle | 0,6393 | 0,9234 | 4,30 / 3,61 |
| $20: saw | 1,1791 | 1,2283 | 4,07 / 3,50 |
| $40: pulse | 1,2150 | 1,2234 | 3,91 / 3,36 |
| $30: triangle+saw | 1,2202 | 1,5634 | 9,89 / 3,63 |
| $50: triangle+pulse | 1,4125 | 1,4378 | 4,38 / 3,47 |
| $60: saw+pulse | 1,0848 | 1,4187 | 9,93 / 3,57 |
| $70: triangle+saw+pulse | 1,0830 | 1,5549 | 9,93 / 3,63 |

Tabellen gäller denna enda patch. Den visar inte bästa möjliga resultat efter ny sökning för respektive vågform. Normaliseringsgain redovisas eftersom ett svagt råljud kan låta mycket starkare i lyssningskopian. [Vågformskvitto](results/waveform-checks/waveform-checks.json).

## Verkligt C64-program i VICE

De tre valda huvudprogrammen exporteras som PAL-PRG och körs i VICE. Registersekvensen och varje relativ cykeltid jämförs med den direkta renderaren; endast en gemensam startförskjutning tillåts. Separat ljudfångst bekräftar att programmen också ger PCM-ljud. Ljudfönstret förankras i registerdumpens klocka och den kända förberedelsen; korrelationssökningen får bara röra sig ±20 ms runt detta ankare. En obegränsad sökning kunde annars välja VICE:s uppstarts- eller initieringsklick. Spelaren håller slutstatus ytterligare 20 ms så att hela instrumentfönstret hinner skrivas till WAV.

| Program | PRG-byte | Patchskrivningar | Största cykelfel | Ljudkorrelation | Gainjusterat NRMSE | Store-only nedre gräns |
| --- | --- | --- | --- | --- | --- | --- |
| Akustisk bastrumma | 4869 | 157 | 0 | 0,7490 | 0,6626 | 0,1195% |
| Virvel | 5125 | 214 | 0 | 0,4721 | 0,8816 | 0,1629% |
| Nylonsträngad gitarr | 4613 | 152 | 0 | 0,9162 | 0,4008 | 0,1157% |

Ljudjämförelsen tillåter en gemensam tidsförskjutning och linjär gain mellan olika emulatorkärnor; den är inte ett bitlikhetsprov. Spelaren blankar skärmen, stänger av avbrott och använder vänteloopar. Store-only-kolumnen räknar bara sex cykler per skrivning, inte parser, IRQ eller grafik. Samtidig grafik, en delad musikspelare och riktiga SID-chip är inte verifierade. [VICE: akustisk bastrumma](results/vice-kick/receipt.json) · [VICE: virvel](results/vice-snare/receipt.json) · [VICE: nylonsträngad gitarr](results/vice-guitar/receipt.json).

## PCM som formatreferens

Det separata PCM-provet kvantiserar till jämna ideala amplitudnivåer vid 8 kHz och återger med zero-order hold. Det modellerar varken SID-DAC:ens olinjäritet, huvudvolymens påverkan på andra röster eller en C64-spelares CPU-kostnad.

| Referens | 4 bit: fel | 4 bit: packade byte | 8 bit: fel | 8 bit: packade byte |
| --- | --- | --- | --- | --- |
| Akustisk bastrumma | 1,7981 | 3200 | 0,2271 | 6400 |
| Virvel | 1,7957 | 3200 | 0,2791 | 6400 |
| Nylonsträngad gitarr | 1,0793 | 3200 | 0,3695 | 6400 |

Det är en jämförelse av informationsförlust, inte ett löfte om samma resultat från $D418 eller Mahoney-utmatning på hårdvara. [PCM-kvitto](results/pcm-reference/receipt.json).

## Vad fungerar, och vad ska lämnas utanför slutsatsen?

Mätkontrollerna har status `pass`. En polaritetsvänd ton fick spektralfel 0,000000 men PCM-MSE 1,280001, vilket visar varför målfunktionerna kan föredra olika program. Den syntetiska återhämtningskontrollen gick från 0,6406 till 0,1764 på 120 kandidater. Samma SID-renderare skapade det målet, så kontrollen visar sökloopens funktion, inte akustisk imitation eller emulatormodellens riktighet. [Mätkontroller](results/search-checks.json).

Behåll den reproducerbara sökloopen, fulla slumpbudgetar, flera frön, råa ljudfiler, upprepade poängmätningar och de verifierade registerprogrammen. Använd den oberoende gitarrtonen och kontinuerliga notföljder när en patch ska bli ett återanvändbart instrument. Välj en filterfri patch eller PCM först efter att ljud och gemensamma hårdvaruresurser vägts mot varandra.

Använd inte resultaten från återanvänd/resetad instans som slutlig metodjämförelse. Tolka inte ett lågt spektralfel som mänskligt godkänd klang, ett urval ur den sammanslagna finalistpoolen som rättvis metodtävling eller ett enstaka tvåröstsförsök som bevis för fler rösters nytta. En isolerad ny SID-instans är inte ett bevis för problemfri återtriggning, och exakt VICE-registertiming är inte ett bevis för fysisk SID-likhet.

## Reproduktion och underlag

[Lyssningssidan](listen.html) innehåller A/B-ljud. [Källor och licenser](references.md) beskriver inspelningarna. [Körningsplanen](results/fresh-sweep/plan.json) innehåller frön, budgetar, källkodshashar och paketversioner. Slutlig artefaktkontroll utförs separat av [verify_lab.py](verify_lab.py); denna rapportgenerator ersätter inte den kontrollen.

Rapporten använder renderarkällan med SHA-256 `ecc5755de95267fb52b5e25084cda7a25907285e4a652306b1e0709532146550`.

```sh
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/sid-inverse/write_findings.py
```

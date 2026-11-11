Konkreta SID-instrument som sökstarter
===================================

Åtta instrument har hämtats från fem riktiga exempelstycken i GoatTracker 2.77. Författarens [officiella verktygssida](https://cadaver.github.io/tools.html) länkar till [distributionen på SourceForge](https://sourceforge.net/projects/goattracker2/files/GoatTracker%202/2.77/GoatTracker_2.77.zip/download). Originalarkivet och dess dokumentation ligger i `sources/sid-examples/`; SHA256 för arkivet och varje vald låt finns i `sid-examples.json`.

| Stycke | Angiven kompositör | Instrument som extraherats | Försök på melodikanalen |
| --- | --- | --- | --- |
| Dojo | Cadaver, Lasse Öörni | Koto #2, Fast Koto #7, Long lead #10 | Korta anslag för MOD-sample13/15 och längre PWM-ton för14 |
| Transylvanian Whipping | Cadaver | Harpsichord #1, Flute #2 | Plockad klang samt mjukare alternativ för13/14/15/16 |
| The Consultant | Cadaver | Pulse lead #3 | Rörlig puls för14 |
| Covert Ops in 2D, funktempo | Cadaver | Sawtooth lead #10 | Ljusare alternativ för14 |
| MW Title Remix, 2x-speed | Cadaver | Lead #4 | Kort testfas följd av sågtand; källan använder dubbla uppdateringsfrekvensen |

Detta är verifierade instrumentdata ur GTS5-filerna, inte en lista med låtnamn som antas låta lika. Parsern läser hela filformatet och kontrollerar att inga bytes blir över. JSON-filen innehåller AD/SR, första kontrollbyte, gate-timer, alla nåbara våg-, puls-, filter- och hastighetstabellrader samt 32 expanderade uppdateringar för varje instrument. Själva likheten med Stardust har ännu inte lyssnats eller mätts över melodifrasen. Förslagen i sista kolumnen är sökstarter.

Två särskilt enkla program att prova är Koto från Dojo och Harpsichord från Transylvanian Whipping. Koto har AD=$04, SR=$7A och initierar med $09. Därefter följer kontrollbytena $51, $41, $41 och $40. Harpsichord har AD=$03, SR=$89 och initierar också med $09; dess tabell följer med $51, $41 och $40. $51 kombinerar triangel och puls. $40 behåller pulsvågformen men släpper gate. En enda statisk pulsvåg bevarar alltså inte hela instrumentet.

De expanderade programmen beskriver fristående noter med pulsposition0 före första tabelluppdateringen. Originalspelaren kan hoppa över pulsuppdateringar vid radgränser beroende på optimeringsinställning. Flöjtens vibrato finns kvar som rå hastighetstabell och fördröjning men är inte expanderat. Inget av de åtta valda instrumenten startar en filtertabell; i en originallåt kan globalt filterläge ha ärvts från en tidigare not. En fristående sökstart stänger därför uttryckligen av filtret. Återgivningen av dessa program över målfrasen återstår.

Distributionens README anger GNU GPL och licensfilen `copying` är bevarad. `src/player.s` har ett separat tillstånd för fri användning av spelarrutinen och skapade låtbinärer. Något separat generellt public-domain-tillstånd för exempelmusikens instrument har inte identifierats. Proveniens ska därför följa med; instrumenten ska inte beskrivas som CC0 eller public domain.

Återskapa extraktionen med `python3 experiments/mod-hybrid/sid_examples.py`. Hjälparen hämtar inget från nätet och kopierar ingen optimeringskod; den läser det redan hämtade originalarkivet och skriver `sid-examples.json`.

En kompletterande genomgång av samma arkivs befintliga låtar finns i `sources/sid-examples/arpeggio-seeds.json`. Där hittades verkliga toncykler: Cadavers Powerchord, instrument12 i Unleash, växlar mellan grundton, kvint och oktav; instrument4 och5 i The Consultant växlar mellan moll- respektive durters, kvint, oktav och grundton. Tre direkt användbara program med64 expanderade uppdateringar finns i `sources/sid-examples/arpeggio-presets.json`. Att ett annat instrument heter chord räcker däremot inte som bevis på arpeggio; vissa namnmatchningar använder andra tekniker.

Dessa toncykler är en möjlig sökstart när en enda statisk vågform saknar rätt fördelning av framträdande deltoner. De bevarar inte flera samtidiga sinuskomponenter exakt. En anpassning till målklangens deltoner4,6 och7 skulle exempelvis kräva relativa lägen kring+24,+31 och+34 halvtoner; det vore en ny anpassning och ska inte tillskrivas originalinstrumentets kompositör.

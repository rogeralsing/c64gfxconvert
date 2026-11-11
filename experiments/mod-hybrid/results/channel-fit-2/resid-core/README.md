reSID-motor som matchar installerad VICE
======================================

Bryggan `channel_resid.py` laddar `libchannel_resid.dylib`, byggd från den oförändrade reSID-koden i den officiella VICE 3.10-utgåvan. [Källarkivet](https://downloads.sourceforge.net/project/vice-emu/releases/vice-3.10.tar.gz) har SHA256 `8e5bac18cbcb9f192380ad3ef881f8790f5b75c41d7b3da65d831985d864d6d1`, samma värde som den installerade Homebrew-formeln. Formeln och `x64sc -features` är sparade här. Källkod och GPL-2.0-or-later-licens följer med.

Inställningarna följer den installerade VICE-körningen: MOS6581, intern och extern filtrering, resampling, passband 90%, gain 97% och filterbias 500mV. Bias 500mV är VICE 3.10:s faktiska standard; äldre körningar använde `-default`. Det vore därför fel att kalla dessa körningar bias 0. Den aktiverade källvarianten `NEW_8580_FILTER=1` används även för 6581, i likhet med installerad VICE. Alla inställningar och källhashar står i `provenance.json`.

`make_sid(rate)` ger ett objekt med `write`, `clock` och `reset`. Reset ersätter hela det inbyggda chipobjektet. Därmed kan oscillator- och kuverthistorik från en tidigare kandidat inte följa med. reSID:s egen lilla dithertabell använder `rand()` vid konstruktion. Fem färska återgivningar skilde högst 5 steg i 16-bitars PCM, ungefär 0,000153 av full skala. Detta är dokumenterat i `benchmark.json`; det är inte samma fel som återanvända oscillatorer. Varm återgivning av en sekund tog median 32,9ms. Den första gemensamma tabellinitieringen tog ungefär 0,53s.

Kalibreringen använder exakt samma frysta 20,5-sekunders program som `first-native-export/frameevents.json`. Alla jämförelser använder ett fast utsnitt 0,5–20,5s. Ingen fri tidsförskjutning eller pitchförändring används i målfunktionen.

| Återgivning | Jämförelse med inspelad VICE |
| --- | --- |
| Faktiska VICE-registerhändelser spelade genom bryggan | Vågformskorrelation 0,999998 och SequenceLoss 0,000954 |
| Källans 200Hz-ramar, med ursprungliga 8 cykler mellan skrivningar | Vågformskorrelation 0,842648 och SequenceLoss 0,04533 |

Samma första kandidats SequenceLoss mot originalfrasen var 0,72502 med bryggans ramåtergivning och 0,71665 i faktisk VICE. Den tidigare reSIDfp-återgivningen gav 0,64377, vilket gav en alltför positiv bedömning av kandidaten. `calibration.json` och de två WAV-filerna behåller underlaget. Siffrorna visar att ljudmotorerna nu överensstämmer; de visar inte att den första kandidaten är musikalisk eller tillräckligt lik originalet.

Återstående skillnad mellan ramåtergivningen och C64-programmet beror bland annat på skrivordningens cykler inom varje 5ms-ram. C64-spelarens faktiska registervärden kontrollerades vid 1ms och 2ms i samtliga 4100 ramar utan avvikelse. Sökningen kan nu använda samma motor som slutlig VICE-lyssning, men slutresultatet ska fortfarande spelas upp och bedömas som en hel fras.

Bygg om med `experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/channel_resid.py`. Hjälparen verifierar arkivets hash och bygger med Clang utan att ändra emulatorns algoritmer. C++-bryggan och den genererade `siddefs.h` är de enda tillagda byggdelarna.

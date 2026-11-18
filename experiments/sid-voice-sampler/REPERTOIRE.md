# Music work queue

Cream of the Earth is the next active port. Hyperbased's three-minute PRG and
four WAVs remain frozen. Adding a queued song does not start its conversion.

| Song | Source | Status | Requested focus |
| --- | --- | --- | --- |
| Hyperbased | [Pinned MOD receipt](../mod-hybrid/sources/hyperbased.source.json) | Preserved | Verified 3:00 ending, normal VICE disk loading and separate SID stems. |
| Cream of the Earth | [Pinned MOD receipt](../mod-hybrid/sources/cream-of-the-earth.source.json) | SID1 candidate; listening pending | Selected 3:08.42 on a stock 64 KiB C64. Frozen oscillator samples on SID2/SID3; native SID1 restores C1 at 17.92–31.36 and uses a new waveform/ADSR program. Later C1 chords remain omitted. Active output: `work/cream/sid1-repair/`. Preserve both earlier full baselines and the approved 17.92–44.80 interval. |
| Druid 2 | [Mod Archive module 125984](https://modarchive.org/index.php?request=view_by_moduleid&query=125984) | Queued | Piano version, as described by the user. Listen and assess after Hyperbased; not converted yet. |

Previously downloaded modules remain under `../mod-hybrid/sources/`. This queue
records the active focus and newly requested songs; it does not replace that
source collection.

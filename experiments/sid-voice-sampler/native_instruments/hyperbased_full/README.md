# Full Hyperbased instrument recipes

Each ASM file contains one reusable instrument declaration. The host arranger reads baseControl and basePulse; peakSustain documents the intended ordinary SID level. The native player receives resolved note/register changes, independently reused PCM banks and triangle tables. These files are not whole-song waveform windows or standalone players.

Instrument 11 requires its actual sample attack; baseControl=0 deliberately prevents a single-partial flute fallback. Pitch roots are measured from the pinned source by full_length_instruments.py; chords 12/13/15/16 retain explicitly approximate arpeggios. Later lead waveforms, pulse widths and sustain envelopes are instrument programs, not claims of original sample fidelity.

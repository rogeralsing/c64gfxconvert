// Cream's continuous-envelope SID states use the shared native mixer contract.
// SID1 carries a compact frequency dictionary index and an explicit continuous
// flag. SID2 carries direct frequency bytes for its percussive sweeps. Both
// sustain/release bytes stay $10 through TEST rests; GATE never drops.
.label voice_record = $0620
.pc = $f800 "Cream native SID state program"
synth_sid_tick:
    ldx tick_record
    lda cream_frequency_low,x
    sta voice_record
    lda cream_frequency_high,x
    sta voice_record+1
    ldx #9
!copy:
    lda tick_record+2,x
    sta voice_record+2,x
    dex
    bpl !copy-
    rts
cream_sid_program_end:

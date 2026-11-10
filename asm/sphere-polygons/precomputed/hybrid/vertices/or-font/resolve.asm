// Only silhouette cells need a final position-dependent remap. Every other
// cell already contains its final coverage-indexed character code.
resolve_screen:
    lda #<clip_records
    sta raster_clip_ptr
    lda #>clip_records
    sta raster_clip_ptr+1
    lda #CLIP_TILE_COUNT
    sta raster_clip_left
!clip:
    ldy #0
    lda (raster_clip_ptr),y
    sta raster_screen_ptr
    iny
    lda (raster_clip_ptr),y
    clc
    adc back_screen_hi
    sta raster_screen_ptr+1
    ldy #0
    lda (raster_screen_ptr),y
    beq !clip_advance+
    tax
    lda coverage_compact,x
    ldy #2
    clc
    adc (raster_clip_ptr),y
    sta raster_remap_ptr
    iny
    lda (raster_clip_ptr),y
    adc #>circle_map
    sta raster_remap_ptr+1
    ldy #0
    lda (raster_remap_ptr),y
    sta (raster_screen_ptr),y
!clip_advance:
    clc
    lda raster_clip_ptr
    adc #4
    sta raster_clip_ptr
    bcc !clip_pointer+
    inc raster_clip_ptr+1
!clip_pointer:
    dec raster_clip_left
    bne !clip-
    rts

raster_mask_bases:
    .for (var row = 0; row < 25; row++) {
        .byte 0,8,16
    }

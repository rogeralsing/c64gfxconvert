// PAL AFLI with an arbitrary monochrome sprite raster layer.
// Each VIC bank holds one image half and eight phase-specific sprite pointers.
* = $2000 "Standalone layered AFLI startup"

.const source = $fb
.const destination = $fd
.const remaining = $f9
.const spriteColor = 1
.const backgroundColor = 0

start:
    sei
    cld
    lda #$2f
    sta $00
    lda #$37
    sta $01
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #0
    sta $d01a
    sta $d015
    sta $d020
    lda #$0f
    sta $d019
    lda $dd02
    ora #3
    sta $dd02

    // Copy backwards because the staging and destination ranges overlap.
    // All 16KB include sprite blocks and pointer tables, not just AFLI bytes.
    lda #$34
    sta $01
    lda #<$c3e7
    sta source
    lda #>$c3e7
    sta source + 1
    lda #<$ffff
    sta destination
    lda #>$ffff
    sta destination + 1
    lda #<$4000
    sta remaining
    lda #>$4000
    sta remaining + 1
    ldy #0
copy:
    lda (source),y
    sta (destination),y
    lda source
    bne decrementSource
    dec source + 1
decrementSource:
    dec source
    lda destination
    bne decrementDestination
    dec destination + 1
decrementDestination:
    dec destination
    lda remaining
    bne decrementRemaining
    dec remaining + 1
decrementRemaining:
    dec remaining
    lda remaining
    ora remaining + 1
    bne copy

    // Install vectors after the full-bank relocation has written their RAM.
    lda #$35
    sta $01
    lda #<nmi
    sta $fffa
    lda #>nmi
    sta $fffb
    jsr prepareSprites
    jsr $0e3f
display:
    jmp display

nmi:
    rti

* = $2090 "Layered AFLI IRQ entry"
timingShim:
    jmp rasterPreamble

* = $2200 "Layered AFLI initial full badline"
rasterPreamble:
    inc $02f0
    lda #2
    sta $dd00                 // Start every image with the upper-half bank.
    lda #52
    sta $d001
    sta $d003
    sta $d005
    sta $d007
    sta $d009
    sta $d00b
    sta $d00d
    sta $d00f
    lda #47
waitForPrimingLine:
    cmp $d012
    bne waitForPrimingLine
    lda #$38
    sta $d011
    lda #$08
    sta $d018
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop

    jmp rasterRows

* = $2400 "Layered sprite setup"
prepareSprites:
    jsr $0dc6
    lda #0
    sta $02f0
    sta $d017
    sta $d01b
    sta $d01c
    sta $d01d
    sta $d021
    .if (backgroundColor != 0) {
        lda #backgroundColor
        sta $d021
    }
    lda #2
    sta $dd00
    lda #$e0
    sta $d010
    lda #136
    sta $d000
    lda #160
    sta $d002
    lda #184
    sta $d004
    lda #208
    sta $d006
    lda #232
    sta $d008
    lda #0
    sta $d00a
    lda #24
    sta $d00c
    lda #48
    sta $d00e
    lda #31
    sta $d001
    sta $d003
    sta $d005
    sta $d007
    sta $d009
    sta $d00b
    sta $d00d
    sta $d00f
    lda #spriteColor
    sta $d027
    sta $d028
    sta $d029
    sta $d02a
    sta $d02b
    sta $d02c
    sta $d02d
    sta $d02e
    lda #$ff
    sta $d015
    rts

* = $2800 "Fourteen-cycle layered AFLI rows"
rasterRows:
row49:
    nop
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row50:
    nop
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row51:
    nop
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row52:
    nop
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row53:
    ldx #73
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row54:
    ldy #$3f
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row55:
    stx $d001
    lda #$78
    sta $d018
    sty $d011
row56:
    ldy #$39
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row57:
    stx $d003
    lda #$18
    sta $d018
    sty $d011
row58:
    ldy #$3b
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row59:
    stx $d005
    lda #$38
    sta $d018
    sty $d011
row60:
    ldy #$3d
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row61:
    stx $d007
    lda #$58
    sta $d018
    sty $d011
row62:
    ldy #$3f
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row63:
    stx $d009
    lda #$78
    sta $d018
    sty $d011
row64:
    ldy #$39
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row65:
    stx $d00b
    lda #$18
    sta $d018
    sty $d011
row66:
    ldy #$3b
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row67:
    stx $d00d
    lda #$38
    sta $d018
    sty $d011
row68:
    ldy #$3d
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row69:
    stx $d00f
    lda #$58
    sta $d018
    sty $d011
row70:
    nop
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row71:
    nop
    lda #$78
    sta $d018
    lda #$3f
    sta $d011
row72:
    nop
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row73:
    nop
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row74:
    ldx #94
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row75:
    ldy #$3c
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row76:
    stx $d001
    lda #$48
    sta $d018
    sty $d011
row77:
    ldy #$3e
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row78:
    stx $d003
    lda #$68
    sta $d018
    sty $d011
row79:
    ldy #$38
    lda #$78
    sta $d018
    lda #$3f
    sta $d011
row80:
    stx $d005
    lda #$08
    sta $d018
    sty $d011
row81:
    ldy #$3a
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row82:
    stx $d007
    lda #$28
    sta $d018
    sty $d011
row83:
    ldy #$3c
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row84:
    stx $d009
    lda #$48
    sta $d018
    sty $d011
row85:
    ldy #$3e
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row86:
    stx $d00b
    lda #$68
    sta $d018
    sty $d011
row87:
    ldy #$38
    lda #$78
    sta $d018
    lda #$3f
    sta $d011
row88:
    stx $d00d
    lda #$08
    sta $d018
    sty $d011
row89:
    ldy #$3a
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row90:
    stx $d00f
    lda #$28
    sta $d018
    sty $d011
row91:
    nop
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row92:
    nop
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row93:
    nop
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row94:
    nop
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row95:
    ldx #115
    lda #$78
    sta $d018
    lda #$3f
    sta $d011
row96:
    ldy #$39
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row97:
    stx $d001
    lda #$18
    sta $d018
    sty $d011
row98:
    ldy #$3b
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row99:
    stx $d003
    lda #$38
    sta $d018
    sty $d011
row100:
    ldy #$3d
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row101:
    stx $d005
    lda #$58
    sta $d018
    sty $d011
row102:
    ldy #$3f
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row103:
    stx $d007
    lda #$78
    sta $d018
    sty $d011
row104:
    ldy #$39
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row105:
    stx $d009
    lda #$18
    sta $d018
    sty $d011
row106:
    ldy #$3b
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row107:
    stx $d00b
    lda #$38
    sta $d018
    sty $d011
row108:
    ldy #$3d
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row109:
    stx $d00d
    lda #$58
    sta $d018
    sty $d011
row110:
    ldy #$3f
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row111:
    stx $d00f
    lda #$78
    sta $d018
    sty $d011
row112:
    nop
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row113:
    nop
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row114:
    nop
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row115:
    nop
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row116:
    ldx #136
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row117:
    ldy #$3e
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row118:
    stx $d001
    lda #$68
    sta $d018
    sty $d011
row119:
    ldy #$38
    lda #$78
    sta $d018
    lda #$3f
    sta $d011
row120:
    stx $d003
    lda #$08
    sta $d018
    sty $d011
row121:
    ldy #$3a
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row122:
    stx $d005
    lda #$28
    sta $d018
    sty $d011
row123:
    ldy #$3c
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row124:
    stx $d007
    lda #$48
    sta $d018
    sty $d011
row125:
    ldy #$3e
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row126:
    stx $d009
    lda #$68
    sta $d018
    sty $d011
row127:
    ldy #$38
    lda #$78
    sta $d018
    lda #$3f
    sta $d011
row128:
    stx $d00b
    lda #$08
    sta $d018
    sty $d011
row129:
    ldy #$3a
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row130:
    stx $d00d
    lda #$28
    sta $d018
    sty $d011
row131:
    ldy #$3c
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row132:
    stx $d00f
    lda #$48
    sta $d018
    sty $d011
row133:
    nop
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row134:
    ldy #$3f
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row135:
    stx $dd00
    lda #$78
    sta $d018
    sty $d011
row136:
    nop
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row137:
    ldx #157
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row138:
    ldy #$3b
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row139:
    stx $d001
    lda #$38
    sta $d018
    sty $d011
row140:
    ldy #$3d
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row141:
    stx $d003
    lda #$58
    sta $d018
    sty $d011
row142:
    ldy #$3f
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row143:
    stx $d005
    lda #$78
    sta $d018
    sty $d011
row144:
    ldy #$39
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row145:
    stx $d007
    lda #$18
    sta $d018
    sty $d011
row146:
    ldy #$3b
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row147:
    stx $d009
    lda #$38
    sta $d018
    sty $d011
row148:
    ldy #$3d
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row149:
    stx $d00b
    lda #$58
    sta $d018
    sty $d011
row150:
    ldy #$3f
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row151:
    stx $d00d
    lda #$78
    sta $d018
    sty $d011
row152:
    ldy #$39
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row153:
    stx $d00f
    lda #$18
    sta $d018
    sty $d011
row154:
    nop
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row155:
    nop
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row156:
    nop
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row157:
    nop
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row158:
    ldx #178
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row159:
    ldy #$38
    lda #$78
    sta $d018
    lda #$3f
    sta $d011
row160:
    stx $d001
    lda #$08
    sta $d018
    sty $d011
row161:
    ldy #$3a
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row162:
    stx $d003
    lda #$28
    sta $d018
    sty $d011
row163:
    ldy #$3c
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row164:
    stx $d005
    lda #$48
    sta $d018
    sty $d011
row165:
    ldy #$3e
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row166:
    stx $d007
    lda #$68
    sta $d018
    sty $d011
row167:
    ldy #$38
    lda #$78
    sta $d018
    lda #$3f
    sta $d011
row168:
    stx $d009
    lda #$08
    sta $d018
    sty $d011
row169:
    ldy #$3a
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row170:
    stx $d00b
    lda #$28
    sta $d018
    sty $d011
row171:
    ldy #$3c
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row172:
    stx $d00d
    lda #$48
    sta $d018
    sty $d011
row173:
    ldy #$3e
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row174:
    stx $d00f
    lda #$68
    sta $d018
    sty $d011
row175:
    nop
    lda #$78
    sta $d018
    lda #$3f
    sta $d011
row176:
    nop
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row177:
    nop
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row178:
    nop
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row179:
    ldx #199
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row180:
    ldy #$3d
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row181:
    stx $d001
    lda #$58
    sta $d018
    sty $d011
row182:
    ldy #$3f
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row183:
    stx $d003
    lda #$78
    sta $d018
    sty $d011
row184:
    ldy #$39
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row185:
    stx $d005
    lda #$18
    sta $d018
    sty $d011
row186:
    ldy #$3b
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row187:
    stx $d007
    lda #$38
    sta $d018
    sty $d011
row188:
    ldy #$3d
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row189:
    stx $d009
    lda #$58
    sta $d018
    sty $d011
row190:
    ldy #$3f
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row191:
    stx $d00b
    lda #$78
    sta $d018
    sty $d011
row192:
    ldy #$39
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row193:
    stx $d00d
    lda #$18
    sta $d018
    sty $d011
row194:
    ldy #$3b
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row195:
    stx $d00f
    lda #$38
    sta $d018
    sty $d011
row196:
    nop
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row197:
    nop
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row198:
    nop
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row199:
    nop
    lda #$78
    sta $d018
    lda #$3f
    sta $d011
row200:
    ldx #220
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row201:
    ldy #$3a
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row202:
    stx $d001
    lda #$28
    sta $d018
    sty $d011
row203:
    ldy #$3c
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row204:
    stx $d003
    lda #$48
    sta $d018
    sty $d011
row205:
    ldy #$3e
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row206:
    stx $d005
    lda #$68
    sta $d018
    sty $d011
row207:
    ldy #$38
    lda #$78
    sta $d018
    lda #$3f
    sta $d011
row208:
    stx $d007
    lda #$08
    sta $d018
    sty $d011
row209:
    ldy #$3a
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row210:
    stx $d009
    lda #$28
    sta $d018
    sty $d011
row211:
    ldy #$3c
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row212:
    stx $d00b
    lda #$48
    sta $d018
    sty $d011
row213:
    ldy #$3e
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row214:
    stx $d00d
    lda #$68
    sta $d018
    sty $d011
row215:
    ldy #$38
    lda #$78
    sta $d018
    lda #$3f
    sta $d011
row216:
    stx $d00f
    lda #$08
    sta $d018
    sty $d011
row217:
    nop
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row218:
    nop
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row219:
    nop
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row220:
    nop
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row221:
    ldx #241
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row222:
    ldy #$3f
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row223:
    stx $d001
    lda #$78
    sta $d018
    sty $d011
row224:
    ldy #$39
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row225:
    stx $d003
    lda #$18
    sta $d018
    sty $d011
row226:
    ldy #$3b
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row227:
    stx $d005
    lda #$38
    sta $d018
    sty $d011
row228:
    ldy #$3d
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row229:
    stx $d007
    lda #$58
    sta $d018
    sty $d011
row230:
    ldy #$3f
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row231:
    stx $d009
    lda #$78
    sta $d018
    sty $d011
row232:
    ldy #$39
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row233:
    stx $d00b
    lda #$18
    sta $d018
    sty $d011
row234:
    ldy #$3b
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row235:
    stx $d00d
    lda #$38
    sta $d018
    sty $d011
row236:
    ldy #$3d
    lda #$48
    sta $d018
    lda #$3c
    sta $d011
row237:
    stx $d00f
    lda #$58
    sta $d018
    sty $d011
row238:
    nop
    lda #$68
    sta $d018
    lda #$3e
    sta $d011
row239:
    nop
    lda #$78
    sta $d018
    lda #$3f
    sta $d011
row240:
    nop
    lda #$08
    sta $d018
    lda #$38
    sta $d011
row241:
    nop
    lda #$18
    sta $d018
    lda #$39
    sta $d011
row242:
    ldx #6
    lda #$28
    sta $d018
    lda #$3a
    sta $d011
row243:
    ldy #$3c
    lda #$38
    sta $d018
    lda #$3b
    sta $d011
row244:
    stx $d001
    lda #$48
    sta $d018
    sty $d011
row245:
    ldy #$3e
    lda #$58
    sta $d018
    lda #$3d
    sta $d011
row246:
    stx $d003
    lda #$68
    sta $d018
    sty $d011
row247:
    ldy #$70
    lda #$78
    sta $d018
    lda #$3f
    sta $d011
rowsEnd:
    sty $d011
    lda #0
    sta $d027
    sta $d028
    sta $d029
    sta $d02a
    sta $d02b
    sta $d02c
    sta $d02d
    sta $d02e
    sta $d015
    lda #31
    sta $d001
    sta $d003
    sta $d005
    sta $d007
    sta $d009
    sta $d00b
    sta $d00d
    sta $d00f
waitHighRaster:
    bit $d011
    bpl waitHighRaster
waitFrameWrap:
    bit $d011
    bmi waitFrameWrap
    lda #1
    sta $d027
    sta $d028
    sta $d029
    sta $d02a
    sta $d02b
    sta $d02c
    sta $d02d
    sta $d02e
    lda #$ff
    sta $d015
    rts

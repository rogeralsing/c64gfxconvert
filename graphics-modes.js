/** Supported presets combine a bitmap format with optional sprite overlays. */
const C64_GRAPHICS_MODES = Object.freeze([
  { id: 'fli', label: 'FLI', format: 'fli', spriteOverlay: false },
  { id: 'fli-sprites', label: 'FLI + Sprites', format: 'fli', spriteOverlay: true },
  { id: 'ifli', label: 'IFLI', format: 'ifli', spriteOverlay: false },
  { id: 'bitmap', label: 'Multi Color Bitmap', format: 'bitmap', spriteOverlay: false },
  { id: 'hires', label: 'Hires', format: 'hires', spriteOverlay: false },
  { id: 'hires-2color', label: 'Hires · 2 colors', format: 'hires', spriteOverlay: false, twoColor: true },
  { id: 'afli', label: 'AFLI', format: 'afli', spriteOverlay: false },
  { id: 'afli-sprites', label: 'AFLI + Sprites', format: 'afli', spriteOverlay: true },
  { id: 'nufli', label: 'NUFLI', format: 'nufli', spriteOverlay: false },
  { id: 'pafli', label: 'PAFLI', format: 'pafli', spriteOverlay: false, leftInset: 28 }
].map(preset => {
  const sourceWidth = ['fli', 'bitmap'].includes(preset.format) ? 160 : 320;
  return Object.freeze({
    ...preset,
    leftInset: preset.leftInset ?? (preset.spriteOverlay ? 112 : ['fli', 'afli', 'ifli'].includes(preset.format) ? 16 : 0),
    sourceWidth,
    restrictedWidth: preset.spriteOverlay || preset.format === 'ifli' ? 320 : sourceWidth
  });
}));

function getC64GraphicsMode(id) {
  const mode = C64_GRAPHICS_MODES.find(preset => preset.id === id);
  if (!mode) throw new Error(`Unknown C64 graphics mode: ${String(id)}.`);
  return mode;
}

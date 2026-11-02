/** Supported presets combine a bitmap format with virtual colors and sprite overlays. */
const C64_GRAPHICS_MODES = Object.freeze([
  { id: 'virtual-fli', label: 'FLI Virtual', format: 'fli',
    virtualColors: true, spriteOverlay: false, virtualRows: true },
  { id: 'virtual-fli-sprites', label: 'FLI Virtual + Sprites', format: 'fli',
    virtualColors: true, spriteOverlay: true, virtualRows: true },
  { id: 'ifli', label: 'IFLI', format: 'ifli',
    virtualColors: true, spriteOverlay: false, virtualRows: false },
  { id: 'virtual-ifli', label: 'IFLI Virtual', format: 'ifli',
    virtualColors: true, spriteOverlay: false, virtualRows: true },
  { id: 'bitmap', label: 'Multi Color Bitmap', format: 'bitmap',
    virtualColors: false, spriteOverlay: false, virtualRows: false },
  { id: 'hires', label: 'Hires', format: 'hires',
    virtualColors: false, spriteOverlay: false, virtualRows: false },
  { id: 'virtual-afli', label: 'AFLI Virtual', format: 'afli',
    virtualColors: true, spriteOverlay: false, virtualRows: true },
  { id: 'virtual-afli-sprites', label: 'AFLI Virtual + Sprites', format: 'afli',
    virtualColors: true, spriteOverlay: true, virtualRows: true },
  { id: 'nufli', label: 'NUFLI', format: 'nufli',
    virtualColors: false, spriteOverlay: false, virtualRows: false },
  { id: 'pafli', label: 'PAFLI', format: 'pafli', leftInset: 28,
    virtualColors: true, spriteOverlay: false, virtualRows: true }
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

/** PAL reference palettes in standard C64 color-index order. */
const C64_PALETTES = [
  {
    id: 'colodore', label: 'Colodore (PAL)',
    // Colodore PAL reference colors, in C64 color-index order.
    // https://github.com/VICE-Team/svn-mirror/blob/main/vice/data/C64/colodore.vpl
    hex: ['000000', 'FFFFFF', '96282E', '5BD6CE', '9F2DAD', '41B936', '2724C4', 'EFF347',
      '9F4815', '5E3500', 'DA5F66', '474747', '787878', '91FF84', '6864FF', 'AEAEAE']
  },
  {
    id: 'pepto', label: 'Pepto (PAL)',
    // https://github.com/VICE-Team/svn-mirror/blob/main/vice/data/C64/pepto-pal.vpl
    hex: ['000000', 'FFFFFF', '68372B', '70A4B2', '6F3D86', '588D43', '352879', 'B8C76F',
      '6F4F25', '433900', '9A6759', '444444', '6C6C6C', '9AD284', '6C5EB5', '959595']
  }
];

/** Keep palette references stable for controls while rebuilding all derived colors. */
function createC64PaletteState(initialId = 'colodore') {
  const names = ['Black', 'White', 'Red', 'Cyan', 'Purple', 'Green', 'Blue', 'Yellow',
    'Orange', 'Brown', 'Light red', 'Dark gray', 'Gray', 'Light green', 'Light blue', 'Light gray'];
  const palette = [];
  const brightnessBands = [];
  const virtualPalette = [];
  let paletteId;

  function select(id) {
    const preset = C64_PALETTES.find(preset => preset.id === id);
    if (!preset) throw new Error('Unknown C64 palette.');
    preset.hex.forEach((hex, index) => {
      const color = { index, name: names[index], hex: `#${hex}`,
        rgb: hex.match(/../g).map(channel => parseInt(channel, 16)) };
      if (palette[index]) Object.assign(palette[index], color);
      else palette.push(color);
    });

    // Dark to light, using the paired brightness columns in the supplied gradient.
    const bands = [
      [0],      // Black
      [6, 9],   // Blue, brown
      [2, 11],  // Red, dark gray
      [4, 8],   // Purple, orange
      [14, 12], // Light blue, gray
      [5, 10],  // Green, light red
      [3, 15],  // Cyan, light gray
      [13, 7],  // Light green, yellow
      [1]       // White
    ].map(indices => {
      const colors = indices.map(index => ({ color: palette[index], lab: rgbToOklab(...palette[index].rgb) }));
      return { lightness: colors.reduce((sum, entry) => sum + entry.lab.lightness, 0) / colors.length, colors };
    });
    brightnessBands.splice(0, brightnessBands.length, ...bands);
    buildIfliVirtualPalette(palette, brightnessBands).forEach((color, index) => {
      if (virtualPalette[index]) Object.assign(virtualPalette[index], color);
      else virtualPalette.push(color);
    });
    paletteId = id;
    return preset;
  }

  select(initialId);
  return { palette, brightnessBands, virtualPalette, select, get id() { return paletteId; } };
}

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
  },
  {
    id: 'peptoette-a', label: 'PEPTOette_a',
    // https://c64gfx.com/api/palettes.json (PEPTOette_a); palettes/peptoette-a.vpl.
    hex: ['000000', 'FFFFFF', '753D3D', '7BB4B4', '7D4488', '5C985C', '343383', 'CBCC7C',
      '7C552F', '523E00', 'A76F6F', '4E4E4E', '767676', '9FDB9F', '6D6CBC', 'A3A3A3']
  }
];

/** Keep palette references stable for controls while rebuilding all derived colors. */
function createC64PaletteState(initialId = 'colodore', initialVirtualColorMode = 'computed') {
  const names = ['Black', 'White', 'Red', 'Cyan', 'Purple', 'Green', 'Blue', 'Yellow',
    'Orange', 'Brown', 'Light red', 'Dark gray', 'Gray', 'Light green', 'Light blue', 'Light gray'];
  const palette = [];
  const brightnessBands = [];
  const virtualPalette = [];
  const virtualPalettes = { computed: [], talent: [] };
  const virtualColorCache = { computed: new Map(), talent: new Map() };
  let paletteId;
  let virtualColorMode = validateVirtualColorMode(initialVirtualColorMode);

  function validateVirtualColorMode(mode) {
    if (mode !== 'computed' && mode !== 'talent') throw new Error('Unknown virtual color mode.');
    return mode;
  }

  function refreshActiveVirtualPalette() {
    virtualPalette.splice(0, virtualPalette.length, ...virtualPalettes[virtualColorMode]);
  }

  function updateVirtualPalette(mode, colors) {
    const cache = virtualColorCache[mode];
    const updated = colors.map(color => {
      if (cache.has(color.index)) Object.assign(cache.get(color.index), color);
      else cache.set(color.index, color);
      return cache.get(color.index);
    });
    virtualPalettes[mode].splice(0, virtualPalettes[mode].length, ...updated);
  }

  function buildTalentVirtualPalette(computed) {
    const computedByPair = new Map(computed.map(color => [color.colorIndices.join('-'), color.index]));
    const bandByColor = new Map();
    for (const [bandIndex, band] of brightnessBands.entries()) {
      for (const entry of band.colors) bandByColor.set(entry.color.index, bandIndex);
    }
    let nextIndex = computed.length;
    return TALENT_PALETTE_DATA.pairs.slice().sort((a, b) =>
      a.colorIndices[0] - b.colorIndices[0] || a.colorIndices[1] - b.colorIndices[1]).map(pair => {
      const [first, second] = pair.colorIndices;
      const key = `${first}-${second}`;
      // Shared pairs keep their Computed IDs. New IDs are stable across base palettes.
      const index = computedByPair.has(key) ? computedByPair.get(key) : nextIndex++;
      const rgb = first === second ? [...palette[first].rgb] : palette[first].rgb.map((channel, position) =>
        Math.round(linearToSrgb((srgbToLinear(channel) + srgbToLinear(palette[second].rgb[position])) / 2)));
      return {
        index,
        id: `ifli-${key}`,
        colorIndices: [first, second],
        brightnessBands: [bandByColor.get(first), bandByColor.get(second)],
        rgb,
        hex: '#' + rgb.map(channel => channel.toString(16).padStart(2, '0')).join('').toUpperCase(),
        count: pair.count,
        imageCount: pair.imageCount
      };
    }).sort((a, b) => a.index - b.index);
  }

  function setVirtualColorMode(mode) {
    validateVirtualColorMode(mode);
    virtualColorMode = mode;
    refreshActiveVirtualPalette();
    return virtualColorMode;
  }

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
    const computed = buildIfliVirtualPalette(palette, brightnessBands);
    updateVirtualPalette('computed', computed);
    updateVirtualPalette('talent', buildTalentVirtualPalette(computed));
    refreshActiveVirtualPalette();
    paletteId = id;
    return preset;
  }

  select(initialId);
  return { palette, brightnessBands, virtualPalette, virtualPalettes, select, setVirtualColorMode,
    get id() { return paletteId; }, get virtualColorMode() { return virtualColorMode; } };
}

/** Buildless UI controllers shared by the converter's graphics modes. */
globalThis.C64ConverterControls = (() => {
  function createPalettePicker({ container, name, palette, value, onChange }) {
    const document = container.ownerDocument;
    const inputs = [];
    let selectedValue = value;
    for (const color of palette) {
      const choice = document.createElement('label');
      choice.className = 'palette-choice';
      choice.title = `${color.index} · ${color.name} · ${color.hex}`;

      const radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = name;
      radio.value = String(color.index);
      radio.className = 'sr-only';
      radio.checked = color.index === value;
      radio.setAttribute('aria-label', color.name);
      radio.addEventListener('change', () => {
        if (!radio.checked) return;
        selectedValue = color.index;
        onChange?.(color);
      });

      const swatch = document.createElement('span');
      swatch.className = 'palette-swatch';
      swatch.style.backgroundColor = color.hex;
      swatch.setAttribute('aria-hidden', 'true');
      choice.append(radio, swatch);
      container.append(choice);
      inputs.push(radio);
    }
    return {
      getValue: () => selectedValue,
      setEnabled(enabled) {
        for (const input of inputs) input.disabled = !enabled;
      }
    };
  }

  function createSpriteOverlayControls({ root, palette, valueElement, value = 1, onChange }) {
    const match = root.querySelector('#sprite-match');
    const dither = root.querySelector('#sprite-dither');
    const matchValue = root.querySelector('#sprite-match-value');
    const ditherValue = root.querySelector('#sprite-dither-value');
    match.max = String(C64_SPRITE_MATCH_MAX * 100);

    const picker = createPalettePicker({
      container: root.querySelector('#sprite-palette'),
      name: 'sprite-color',
      palette,
      value,
      onChange(color) {
        updateColorValue(color);
        onChange?.(getState());
      }
    });

    function getState() {
      return {
        colorIndex: picker.getValue(),
        matchAmount: match.valueAsNumber / 100,
        ditherAmount: dither.valueAsNumber / 100
      };
    }

    function updateColorValue(color) {
      valueElement.textContent = `${color.index} · ${color.name} · ${color.hex}`;
    }

    function updateSliderLabels() {
      matchValue.value = `${match.value}%`;
      ditherValue.value = `${dither.value}%`;
      match.setAttribute('aria-valuetext', `${match.value}% sprite match range`);
      dither.setAttribute('aria-valuetext', `${dither.value}% sprite dither strength`);
    }

    function setVisible(visible) {
      root.hidden = !visible;
      picker.setEnabled(visible);
      match.disabled = !visible;
      dither.disabled = !visible;
    }

    for (const slider of [match, dither]) {
      slider.addEventListener('input', () => {
        updateSliderLabels();
        onChange?.(getState());
      });
    }
    updateColorValue(palette.find(color => color.index === value));
    updateSliderLabels();
    setVisible(!root.hidden);
    return { getState, setVisible };
  }

  function createVirtualPaletteView({ root, palette, basePalette }) {
    const document = root.ownerDocument;
    const swatches = root.querySelector('.virtual-palette-swatches');
    const baseColors = new Map(basePalette.map(color => [color.index, color]));
    root.querySelector('.virtual-palette-count').textContent = palette.length;
    const sorted = [...palette].sort((first, second) =>
      first.brightnessBands[0] + first.brightnessBands[1] - second.brightnessBands[0] - second.brightnessBands[1]
      || first.index - second.index);
    let row;
    let previousBrightness = -1;
    for (const color of sorted) {
      const brightness = color.brightnessBands[0] + color.brightnessBands[1];
      if (brightness !== previousBrightness) {
        row = document.createElement('div');
        row.className = 'virtual-palette-row';
        row.setAttribute('role', 'presentation');
        row.dataset.brightness = String(brightness);
        swatches.append(row);
        previousBrightness = brightness;
      }
      const names = [...new Set(color.colorIndices)].map(index => baseColors.get(index).name).join(' + ');
      const label = `${color.index} · ${names} · ${color.hex}`;
      const swatch = document.createElement('span');
      swatch.className = 'virtual-palette-swatch';
      swatch.style.backgroundColor = color.hex;
      swatch.dataset.virtualColor = color.id;
      swatch.title = label;
      swatch.setAttribute('role', 'listitem');
      swatch.setAttribute('aria-label', label);
      row.append(swatch);
    }
    return {
      setVisible(visible) {
        root.hidden = !visible;
      }
    };
  }

  return { createPalettePicker, createSpriteOverlayControls, createVirtualPaletteView };
})();

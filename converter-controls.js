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

  function createVirtualPaletteView({ root, palette, basePalette, onChange }) {
    const document = root.ownerDocument;
    const swatches = root.querySelector('.virtual-palette-swatches');
    const darkest = root.querySelector('#palette-darkest');
    const lightest = root.querySelector('#palette-lightest');
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
        const level = document.createElement('span');
        level.className = 'virtual-palette-level';
        level.textContent = String(brightness);
        level.setAttribute('aria-hidden', 'true');
        row.append(level);
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
      swatch.setAttribute('aria-label', `Level ${brightness} · ${label}`);
      row.append(swatch);
    }

    function getLimits() {
      return { minLevel: darkest.valueAsNumber, maxLevel: lightest.valueAsNumber };
    }

    function updateLimits() {
      const { minLevel, maxLevel } = getLimits();
      root.querySelector('#palette-darkest-value').value = String(minLevel);
      root.querySelector('#palette-lightest-value').value = String(maxLevel);
      darkest.setAttribute('aria-valuetext', `Virtual brightness level ${minLevel} of 16`);
      lightest.setAttribute('aria-valuetext', `Virtual brightness level ${maxLevel} of 16`);
      for (const row of swatches.children) {
        const level = Number(row.dataset.brightness);
        row.classList.toggle('is-outside-range', level < minLevel || level > maxLevel);
      }
    }

    for (const input of [darkest, lightest]) {
      input.addEventListener('input', () => {
        if (darkest.valueAsNumber > lightest.valueAsNumber) {
          if (input === darkest) darkest.value = lightest.value;
          else lightest.value = darkest.value;
        }
        updateLimits();
        onChange?.(getLimits());
      });
    }
    updateLimits();
    return {
      getLimits,
      setVisible(visible) {
        root.hidden = !visible;
        darkest.disabled = !visible;
        lightest.disabled = !visible;
      }
    };
  }

  function createLevelsControls({ root, onChange }) {
    const black = root.querySelector('#levels-black');
    const white = root.querySelector('#levels-white');
    const gamma = root.querySelector('#levels-gamma');
    const chart = root.querySelector('#levels-histogram');
    const context = chart.getContext('2d');
    const histogram = new Float64Array(256);
    const styles = root.ownerDocument.defaultView.getComputedStyle(root);
    const accent = styles.getPropertyValue('--accent').trim();
    const mint = styles.getPropertyValue('--mint').trim();
    const line = styles.getPropertyValue('--line').trim();

    function getState() {
      return { blackPoint: black.valueAsNumber, whitePoint: white.valueAsNumber, gamma: gamma.valueAsNumber };
    }

    function draw() {
      const state = getState();
      const lookup = createSourceLevelsLookup(state);
      const width = chart.width;
      const bottom = chart.height - 18;
      const top = 4;
      const x = value => 1 + value / 255 * (width - 2);
      const y = value => bottom - value / 255 * (bottom - top);
      const peak = Math.max(1, ...histogram);
      context.clearRect(0, 0, chart.width, chart.height);
      context.fillStyle = line;
      for (let bin = 0; bin < 256; bin += 1) {
        const height = histogram[bin] / peak * (bottom - top);
        context.fillRect(x(bin), bottom - height, Math.max(1, width / 256), height);
      }
      context.strokeStyle = mint;
      context.lineWidth = 1;
      context.setLineDash([2, 3]);
      for (const value of [state.blackPoint, state.whitePoint]) {
        context.beginPath();
        context.moveTo(x(value), top);
        context.lineTo(x(value), bottom);
        context.stroke();
      }
      context.setLineDash([]);
      context.strokeStyle = accent;
      context.lineWidth = 2;
      context.beginPath();
      for (let value = 0; value < 256; value += 1) {
        if (value === 0) context.moveTo(x(value), y(lookup[value]));
        else context.lineTo(x(value), y(lookup[value]));
      }
      context.stroke();
      const gradient = context.createLinearGradient(0, 0, width, 0);
      gradient.addColorStop(0, '#000000');
      gradient.addColorStop(1, '#ffffff');
      context.fillStyle = gradient;
      context.fillRect(0, bottom + 5, width, 6);
      const middle = state.blackPoint + (state.whitePoint - state.blackPoint) * 0.5 ** state.gamma;
      for (const [value, color] of [[state.blackPoint, mint], [middle, accent], [state.whitePoint, mint]]) {
        context.fillStyle = color;
        context.beginPath();
        context.moveTo(x(value), bottom + 1);
        context.lineTo(x(value) - 3, bottom + 5);
        context.lineTo(x(value) + 3, bottom + 5);
        context.closePath();
        context.fill();
      }
    }

    function updateLabels() {
      root.querySelector('#levels-black-value').value = black.value;
      root.querySelector('#levels-white-value').value = white.value;
      root.querySelector('#levels-gamma-value').value = gamma.valueAsNumber.toFixed(2);
      black.setAttribute('aria-valuetext', `${black.value} input black point`);
      white.setAttribute('aria-valuetext', `${white.value} input white point`);
      gamma.setAttribute('aria-valuetext', `${gamma.valueAsNumber.toFixed(2)} midtone gamma`);
      draw();
    }

    for (const input of [black, white, gamma]) {
      input.addEventListener('input', () => {
        if (black.valueAsNumber >= white.valueAsNumber) {
          if (input === black) black.value = String(white.valueAsNumber - 1);
          else white.value = String(black.valueAsNumber + 1);
        }
        updateLabels();
        onChange?.(getState());
      });
    }
    root.querySelector('#reset-levels').addEventListener('click', () => {
      black.value = '0';
      white.value = '255';
      gamma.value = '1';
      updateLabels();
      onChange?.(getState());
    });
    updateLabels();
    return {
      getState,
      setSource(source) {
        histogram.fill(0);
        if (source) {
          for (let offset = 0; offset < source.data.length; offset += 4) {
            const weight = source.data[offset + 3] / 255;
            for (let channel = 0; channel < 3; channel += 1) histogram[source.data[offset + channel]] += weight;
          }
        }
        draw();
      }
    };
  }

  return { createPalettePicker, createSpriteOverlayControls, createVirtualPaletteView, createLevelsControls };
})();

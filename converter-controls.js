/** Buildless UI controllers shared by the converter's graphics modes. */
globalThis.C64ConverterControls = (() => {
  function createPalettePicker({ container, name, palette, value, onChange }) {
    const document = container.ownerDocument;
    const inputs = [];
    const swatches = [];
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
      swatches.push({ color, choice, swatch });
    }
    return {
      getValue: () => selectedValue,
      refreshPalette() {
        for (const { color, choice, swatch } of swatches) {
          choice.title = `${color.index} · ${color.name} · ${color.hex}`;
          swatch.style.backgroundColor = color.hex;
        }
      },
      setValue(value) {
        if (!inputs.some(input => input.value === String(value))) throw new Error('Unknown palette color.');
        selectedValue = value;
        for (const input of inputs) input.checked = input.value === String(value);
      },
      setEnabled(enabled) {
        for (const input of inputs) input.disabled = !enabled;
      }
    };
  }

  function createSpriteOverlayControls({ root, palette, valueElement, value = 1, paletteContainer, onChange }) {
    const match = root.querySelector('#sprite-match');
    const dither = root.querySelector('#sprite-dither');
    const matchValue = root.querySelector('#sprite-match-value');
    const ditherValue = root.querySelector('#sprite-dither-value');
    match.max = String(C64_SPRITE_MATCH_MAX * 100);

    const picker = createPalettePicker({
      container: paletteContainer || root.querySelector('#sprite-palette'),
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
    return {
      getState, setVisible,
      refreshPalette() {
        picker.refreshPalette();
        updateColorValue(palette.find(color => color.index === picker.getValue()));
      },
      setColorIndex(index) {
        picker.setValue(index);
        updateColorValue(palette.find(color => color.index === index));
      },
      setState({ matchAmount, ditherAmount }) {
        match.value = String(matchAmount * 100);
        dither.value = String(ditherAmount * 100);
        updateSliderLabels();
      }
    };
  }

  function createVirtualPaletteView({ root, palette, basePalette, getMode = () => 'computed', getToneModel,
      getTalentPalette = () => palette, onChange }) {
    const document = root.ownerDocument;
    const swatches = root.querySelector('.virtual-palette-swatches');
    const darkest = root.querySelector('#palette-darkest');
    const lightest = root.querySelector('#palette-lightest');
    const baseColors = new Map(basePalette.map(color => [color.index, color]));
    const excludedIndices = new Set();
    const buttons = new Map();
    let settings = { minLevel: 0, maxLevel: 16, minLightness: 0, maxLightness: 100 };
    const talent = () => getMode() === 'talent';
    const colorLevel = color => talent() ? color.lightness * 100
      : color.brightnessBands[0] + color.brightnessBands[1];

    function createSwatch(color) {
      const names = [...new Set(color.colorIndices)].map(index => baseColors.get(index).name).join(' + ');
      const label = `${color.index} · ${names} · ${color.hex}`;
      const swatch = document.createElement('button');
      swatch.type = 'button';
      swatch.className = 'virtual-palette-swatch';
      swatch.style.backgroundColor = color.hex;
      swatch.dataset.virtualColor = color.id;
      swatch.title = label;
      swatch.setAttribute('aria-label', talent()
        ? `Lightness ${(color.lightness * 100).toFixed(1)}% · ${label}`
        : `Level ${colorLevel(color)} · ${label}`);
      swatch.addEventListener('click', () => {
        if (swatch.getAttribute('aria-disabled') === 'true') return;
        if (excludedIndices.has(color.index)) excludedIndices.delete(color.index);
        else excludedIndices.add(color.index);
        updateLimits();
        onChange?.(getSettings());
      });
      if (!buttons.has(color.index)) buttons.set(color.index, []);
      buttons.get(color.index).push({ swatch, label, color });
      return swatch;
    }

    function renderSwatches() {
      swatches.replaceChildren();
      buttons.clear();
      swatches.classList.toggle('talent-palette-scales', talent());
      swatches.setAttribute('aria-label', talent() ? 'Observed Talent scales, black to white' : 'Virtual color brightness rows');
      if (talent()) {
        const byIndex = new Map(palette.map(color => [color.index, color]));
        for (const [index, ramp] of (getToneModel?.().ramps ?? []).entries()) {
          const column = document.createElement('div');
          column.className = 'talent-palette-scale';
          column.setAttribute('role', 'group');
          column.setAttribute('aria-label', `Observed scale ${index + 1}, ${ramp.indices.length} tones, black to white`);
          for (const colorIndex of ramp.indices) {
            const color = byIndex.get(colorIndex);
            if (color) column.append(createSwatch(color));
          }
          swatches.append(column);
        }
        const additional = palette.filter(color => !buttons.has(color.index))
          .sort((first, second) => first.lightness - second.lightness || first.index - second.index);
        if (additional.length) {
          const column = document.createElement('div');
          column.className = 'talent-palette-scale';
          column.setAttribute('role', 'group');
          column.setAttribute('aria-label', 'Additional Talent colors');
          for (const color of additional) column.append(createSwatch(color));
          swatches.append(column);
        }
        return;
      }
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
        row.append(createSwatch(color));
      }
    }

    function getLimits() {
      return { min: darkest.valueAsNumber, max: lightest.valueAsNumber };
    }

    function getSettings() {
      if (talent()) Object.assign(settings, { minLightness: darkest.valueAsNumber, maxLightness: lightest.valueAsNumber });
      else Object.assign(settings, { minLevel: darkest.valueAsNumber, maxLevel: lightest.valueAsNumber });
      return { ...settings, excludedIndices: [...excludedIndices] };
    }

    function enabledInRange({ min, max } = getLimits()) {
      return palette.filter(color => {
        const level = colorLevel(color);
        return !excludedIndices.has(color.index) && level >= min - 1e-5 && level <= max + 1e-5;
      });
    }

    function updateLimits() {
      const { min, max } = getLimits();
      const enabled = enabledInRange();
      const count = palette.filter(color => !excludedIndices.has(color.index)).length;
      root.querySelector('.virtual-palette-count').textContent = count < palette.length ? `${count} / ${palette.length}` : count;
      root.querySelector('#palette-darkest-value').value = `${min}${talent() ? '%' : ''}`;
      root.querySelector('#palette-lightest-value').value = `${max}${talent() ? '%' : ''}`;
      darkest.setAttribute('aria-valuetext', talent() ? `Minimum lightness ${min}%` : `Virtual brightness level ${min} of 16`);
      lightest.setAttribute('aria-valuetext', talent() ? `Maximum lightness ${max}%` : `Virtual brightness level ${max} of 16`);
      if (!talent()) for (const row of swatches.children) {
        const level = Number(row.dataset.brightness);
        row.classList.toggle('is-outside-range', level < min || level > max);
      }
      for (const [index, entries] of buttons) {
        const excluded = excludedIndices.has(index);
        const last = enabled.length === 1 && enabled[0].index === index;
        for (const { swatch, label, color } of entries) {
          swatch.setAttribute('aria-pressed', String(!excluded));
          swatch.setAttribute('aria-disabled', String(last));
          swatch.classList.toggle('is-outside-range', colorLevel(color) < min - 1e-5 || colorLevel(color) > max + 1e-5);
          swatch.title = `${label}${excluded ? ' · Disabled' : last ? ' · At least one color must remain enabled in this brightness range' : ''}`;
        }
      }
    }

    function restoreLimits() {
      for (const input of [darkest, lightest]) input.max = talent() ? '100' : '16';
      root.querySelector('.virtual-palette-title').textContent = talent() ? 'Observed scales' : 'Virtual palette';
      root.querySelector('.talent-palette-help').hidden = !talent();
      root.querySelector('label[for="palette-darkest"]').textContent = talent() ? 'Darkest lightness' : 'Darkest level';
      root.querySelector('label[for="palette-lightest"]').textContent = talent() ? 'Lightest lightness' : 'Lightest level';
      darkest.value = String(talent() ? settings.minLightness : settings.minLevel);
      lightest.value = String(talent() ? settings.maxLightness : settings.maxLevel);
      previousLimits = getLimits();
    }

    let previousLimits = getLimits();
    for (const input of [darkest, lightest]) {
      input.addEventListener('input', () => {
        if (darkest.valueAsNumber > lightest.valueAsNumber) {
          if (input === darkest) darkest.value = lightest.value;
          else lightest.value = darkest.value;
        }
        if (enabledInRange().length === 0) {
          darkest.value = String(previousLimits.min);
          lightest.value = String(previousLimits.max);
          updateLimits();
          const announcement = document.getElementById('announcement');
          if (announcement) announcement.textContent = 'Enable a color in that brightness range first.';
          return;
        }
        previousLimits = getLimits();
        updateLimits();
        onChange?.(getSettings());
      });
    }
    renderSwatches();
    updateLimits();
    return {
      getSettings,
      refreshPalette() {
        restoreLimits();
        renderSwatches();
        updateLimits();
      },
      setSettings({ minLevel = 0, maxLevel = 16, excludedIndices: excluded = [], ...lightnessLimits }) {
        const migrated = typeof getTalentLightnessLimits === 'function'
          ? getTalentLightnessLimits({ minLevel, maxLevel, ...lightnessLimits }, getTalentPalette())
          : { minLightness: 0, maxLightness: 100 };
        settings = { minLevel, maxLevel, ...migrated, ...lightnessLimits };
        restoreLimits();
        excludedIndices.clear();
        for (const index of excluded) excludedIndices.add(index);
        previousLimits = getLimits();
        updateLimits();
      },
      setVisible(visible) {
        root.hidden = !visible;
        darkest.disabled = !visible;
        lightest.disabled = !visible;
        for (const entries of buttons.values()) for (const { swatch } of entries) swatch.disabled = !visible;
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
      setState({ blackPoint, whitePoint, gamma: middle }) {
        black.value = String(blackPoint);
        white.value = String(whitePoint);
        gamma.value = String(middle);
        updateLabels();
      },
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

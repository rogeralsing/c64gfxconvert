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
    const pointInput = root.querySelector('#levels-curve-input');
    const pointOutput = root.querySelector('#levels-curve-output');
    const removePoint = root.querySelector('#levels-curve-delete');
    const pointStatus = root.querySelector('#levels-curve-status');
    const resetCurve = root.querySelector('#reset-curve');
    const context = chart.getContext('2d');
    const histogram = Array.from({ length: 3 }, () => new Float64Array(256));
    const view = root.ownerDocument.defaultView;
    const styles = view.getComputedStyle(root);
    const accent = styles.getPropertyValue('--accent').trim();
    const line = styles.getPropertyValue('--line').trim();
    const muted = styles.getPropertyValue('--muted').trim();
    const identity = () => [{ input: 0, output: 0 }, { input: 255, output: 255 }];
    let curvePoints = identity();
    let selected = 0;
    let drag = null;

    chart.tabIndex = 0;
    chart.setAttribute('role', 'group');
    chart.setAttribute('aria-roledescription', 'tone curve editor');
    chart.title = 'Click to add. Drag to move. Arrow keys adjust; Page Up/Page Down select points; Insert adds; Delete removes.';

    function getState() {
      return { blackPoint: black.valueAsNumber, whitePoint: white.valueAsNumber, gamma: gamma.valueAsNumber,
        curvePoints: curvePoints.map(point => ({ ...point })) };
    }

    function geometry() {
      const scale = chart.width / (chart.clientWidth || 256);
      return { scale, left: 14 * scale, right: chart.width - 12 * scale,
        top: 12 * scale, bottom: chart.height - 23 * scale };
    }

    function draw() {
      const density = view.devicePixelRatio || 1;
      const width = Math.round((chart.clientWidth || 256) * density);
      const height = Math.round((chart.clientHeight || 220) * density);
      if (chart.width !== width) chart.width = width;
      if (chart.height !== height) chart.height = height;
      const { left, right, top, bottom, scale } = geometry();
      const x = value => left + value / 255 * (right - left);
      const y = value => bottom - value / 255 * (bottom - top);
      const state = getState();
      const lookup = createSourceCurveLookup(curvePoints);
      const levelsLookup = createSourceLevelsLookup({ blackPoint: state.blackPoint,
        whitePoint: state.whitePoint, gamma: state.gamma });
      const leveledHistogram = histogram.map(channel => {
        const bins = new Float64Array(256);
        for (let value = 0; value < 256; value += 1) bins[levelsLookup[value]] += channel[value];
        return bins;
      });
      const peak = Math.max(1, ...leveledHistogram.flatMap(channel => Array.from(channel)));
      context.clearRect(0, 0, chart.width, chart.height);
      context.strokeStyle = line;
      context.lineWidth = scale;
      for (let division = 0; division <= 4; division += 1) {
        const value = division / 4 * 255;
        context.beginPath();
        context.moveTo(x(value), top);
        context.lineTo(x(value), bottom);
        context.moveTo(left, y(value));
        context.lineTo(right, y(value));
        context.stroke();
      }
      for (const [channel, color] of ['#df7878', '#82b588', '#7b9ed0'].entries()) {
        context.fillStyle = color;
        context.globalAlpha = 0.24;
        context.beginPath();
        context.moveTo(left, bottom);
        for (let value = 0; value < 256; value += 1) {
          context.lineTo(x(value), bottom - leveledHistogram[channel][value] / peak * (bottom - top));
        }
        context.lineTo(right, bottom);
        context.closePath();
        context.fill();
      }
      context.globalAlpha = 1;
      context.strokeStyle = muted;
      context.lineWidth = scale;
      context.setLineDash([3 * scale, 4 * scale]);
      context.beginPath();
      context.moveTo(left, bottom);
      context.lineTo(right, top);
      context.stroke();
      context.setLineDash([]);
      context.strokeStyle = accent;
      context.lineWidth = 2 * scale;
      context.beginPath();
      for (let value = 0; value < 256; value += 1) {
        if (value === 0) context.moveTo(x(value), y(lookup[value]));
        else context.lineTo(x(value), y(lookup[value]));
      }
      context.stroke();
      for (const [index, point] of curvePoints.entries()) {
        context.beginPath();
        context.arc(x(point.input), y(point.output), (index === selected ? 5 : 3.5) * scale, 0, Math.PI * 2);
        context.fillStyle = index === selected ? accent : '#222222';
        context.fill();
        context.strokeStyle = index === selected ? '#ffffff' : accent;
        context.lineWidth = 1.5 * scale;
        context.stroke();
      }
      const gradient = context.createLinearGradient(left, 0, right, 0);
      gradient.addColorStop(0, '#000000');
      gradient.addColorStop(1, '#ffffff');
      context.fillStyle = gradient;
      context.fillRect(left, bottom + 8 * scale, right - left, 5 * scale);
    }

    function updatePointControls() {
      const point = curvePoints[selected];
      const endpoint = selected === 0 || selected === curvePoints.length - 1;
      pointInput.min = String(endpoint ? point.input : curvePoints[selected - 1].input + 1);
      pointInput.max = String(endpoint ? point.input : curvePoints[selected + 1].input - 1);
      pointInput.value = String(point.input);
      pointInput.disabled = endpoint;
      pointOutput.value = String(point.output);
      removePoint.disabled = endpoint;
      resetCurve.disabled = curvePoints.length === 2 && curvePoints[0].output === 0 && curvePoints[1].output === 255;
      pointStatus.textContent = `Point ${selected + 1} of ${curvePoints.length}`;
      chart.setAttribute('aria-label', `Tone curve, point ${selected + 1} of ${curvePoints.length}, ` +
        `input ${point.input}, output ${point.output}. Arrow keys adjust; Page Up and Page Down select; ` +
        'Insert adds a point; Delete removes a point.');
    }

    function updateLabels() {
      root.querySelector('#levels-black-value').value = black.value;
      root.querySelector('#levels-white-value').value = white.value;
      root.querySelector('#levels-gamma-value').value = gamma.valueAsNumber.toFixed(2);
      black.setAttribute('aria-valuetext', `${black.value} input black point`);
      white.setAttribute('aria-valuetext', `${white.value} input white point`);
      gamma.setAttribute('aria-valuetext', `${gamma.valueAsNumber.toFixed(2)} midtone gamma`);
      updatePointControls();
      draw();
    }

    function changed() {
      updatePointControls();
      draw();
      onChange?.(getState());
    }

    function movePoint(input, output) {
      const point = curvePoints[selected];
      if (!Number.isFinite(input)) input = point.input;
      if (!Number.isFinite(output)) output = point.output;
      const nextInput = selected === 0 || selected === curvePoints.length - 1 ? point.input
        : Math.max(curvePoints[selected - 1].input + 1,
          Math.min(curvePoints[selected + 1].input - 1, Math.round(input)));
      const nextOutput = Math.max(0, Math.min(255, Math.round(output)));
      if (point.input === nextInput && point.output === nextOutput) return;
      point.input = nextInput;
      point.output = nextOutput;
      changed();
    }

    function deleteSelectedPoint() {
      if (selected === 0 || selected === curvePoints.length - 1) return;
      curvePoints.splice(selected, 1);
      selected = Math.min(selected, curvePoints.length - 1);
      changed();
    }

    function position(event) {
      const rect = chart.getBoundingClientRect();
      const x = (event.clientX - rect.left - chart.clientLeft) / chart.clientWidth * chart.width;
      const y = (event.clientY - rect.top - chart.clientTop) / chart.clientHeight * chart.height;
      const { left, right, top, bottom } = geometry();
      return { x, y, inside: x >= left && x <= right && y >= top && y <= bottom,
        input: Math.max(0, Math.min(255, Math.round((x - left) / (right - left) * 255))),
        output: Math.max(0, Math.min(255, Math.round((bottom - y) / (bottom - top) * 255))) };
    }

    function hitPoint(position) {
      const { left, right, top, bottom, scale } = geometry();
      let nearest = -1;
      let minimum = (11 * scale) ** 2;
      for (const [index, point] of curvePoints.entries()) {
        const x = left + point.input / 255 * (right - left);
        const y = bottom - point.output / 255 * (bottom - top);
        const distance = (position.x - x) ** 2 + (position.y - y) ** 2;
        if (distance < minimum) { minimum = distance; nearest = index; }
      }
      return nearest;
    }

    function finishDrag(event) {
      if (!drag || event && event.pointerId !== drag.pointerId) return;
      const pointerId = drag.pointerId;
      drag = null;
      chart.classList.remove('is-dragging');
      if (chart.hasPointerCapture(pointerId)) chart.releasePointerCapture(pointerId);
    }

    chart.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      const target = position(event);
      const hit = hitPoint(target);
      if (hit < 0 && !target.inside) return;
      event.preventDefault();
      event.stopPropagation();
      chart.focus({ preventScroll: true });
      if (hit >= 0) {
        selected = hit;
        updatePointControls();
        draw();
      } else {
        const existing = curvePoints.findIndex(point => point.input === target.input);
        if (existing >= 0) {
          selected = existing;
          movePoint(target.input, target.output);
          updatePointControls();
          draw();
        } else {
          selected = curvePoints.findIndex(point => point.input > target.input);
          curvePoints.splice(selected, 0, { input: target.input, output: target.output });
          changed();
        }
      }
      drag = { pointerId: event.pointerId };
      chart.classList.add('is-dragging');
      chart.setPointerCapture(event.pointerId);
    });
    chart.addEventListener('pointermove', event => {
      const target = position(event);
      if (!drag) {
        chart.style.cursor = hitPoint(target) >= 0 ? 'grab' : 'crosshair';
        return;
      }
      if (event.pointerId !== drag.pointerId) return;
      event.preventDefault();
      movePoint(target.input, target.output);
    });
    for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) chart.addEventListener(type, finishDrag);
    chart.addEventListener('dblclick', event => {
      const hit = hitPoint(position(event));
      if (hit < 0) return;
      event.preventDefault();
      selected = hit;
      deleteSelectedPoint();
    });
    chart.addEventListener('keydown', event => {
      const point = curvePoints[selected];
      const step = event.shiftKey ? 10 : 1;
      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        deleteSelectedPoint();
      } else if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
        event.preventDefault();
        movePoint(point.input + (event.key === 'ArrowRight' ? step : event.key === 'ArrowLeft' ? -step : 0),
          point.output + (event.key === 'ArrowUp' ? step : event.key === 'ArrowDown' ? -step : 0));
      } else if (['PageUp', 'PageDown', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        selected = event.key === 'Home' ? 0 : event.key === 'End' ? curvePoints.length - 1
          : Math.max(0, Math.min(curvePoints.length - 1, selected + (event.key === 'PageDown' ? 1 : -1)));
        updatePointControls();
        draw();
      } else if (event.key === 'Insert' || event.key === 'Enter') {
        event.preventDefault();
        const left = Math.min(selected, curvePoints.length - 2);
        const input = Math.round((curvePoints[left].input + curvePoints[left + 1].input) / 2);
        if (input <= curvePoints[left].input || input >= curvePoints[left + 1].input) return;
        const output = createSourceCurveLookup(curvePoints)[input];
        selected = left + 1;
        curvePoints.splice(selected, 0, { input, output });
        changed();
      }
    });
    pointInput.addEventListener('input', () => {
      const value = pointInput.valueAsNumber;
      if (Number.isFinite(value) && value >= Number(pointInput.min) && value <= Number(pointInput.max)) {
        movePoint(value, curvePoints[selected].output);
      }
    });
    pointOutput.addEventListener('input', () => {
      const value = pointOutput.valueAsNumber;
      if (Number.isFinite(value) && value >= 0 && value <= 255) movePoint(curvePoints[selected].input, value);
    });
    for (const input of [pointInput, pointOutput]) input.addEventListener('change', () => {
      movePoint(pointInput.valueAsNumber, pointOutput.valueAsNumber);
      updatePointControls();
    });
    removePoint.addEventListener('click', deleteSelectedPoint);
    resetCurve.addEventListener('click', () => {
      finishDrag();
      curvePoints = identity();
      selected = 0;
      changed();
    });
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
      finishDrag();
      black.value = '0';
      white.value = '255';
      gamma.value = '1';
      curvePoints = identity();
      selected = 0;
      updateLabels();
      onChange?.(getState());
    });
    updateLabels();
    if (view.ResizeObserver) new view.ResizeObserver(draw).observe(chart);
    return {
      getState,
      setState({ blackPoint, whitePoint, gamma: middle, curvePoints: points = identity() }) {
        createSourceCurveLookup(points);
        finishDrag();
        black.value = String(blackPoint);
        white.value = String(whitePoint);
        gamma.value = String(middle);
        curvePoints = points.map(point => ({ ...point }));
        selected = Math.min(selected, curvePoints.length - 1);
        updateLabels();
      },
      setSource(source) {
        for (const channel of histogram) channel.fill(0);
        if (source) {
          for (let offset = 0; offset < source.data.length; offset += 4) {
            const weight = source.data[offset + 3] / 255;
            for (let channel = 0; channel < 3; channel += 1) histogram[channel][source.data[offset + channel]] += weight;
          }
        }
        draw();
      }
    };
  }

  return { createPalettePicker, createSpriteOverlayControls, createVirtualPaletteView, createLevelsControls };
})();

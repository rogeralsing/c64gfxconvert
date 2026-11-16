/** Whole-image border sprite controls, independent of the selected layer. */
function createC64BorderSpriteControls({ root, palette, onChange }) {
  const fieldset = root.querySelector('#border-sprite-controls');
  const summary = root.querySelector('#border-summary');
  const sharedColors = root.querySelector('#border-shared-colors');
  const multicolorSettings = root.querySelector('#border-multicolor-settings');
  const interlaceHelp = root.querySelector('#border-interlace-help');
  const optimizeColors = root.querySelector('#border-optimize-colors');
  const verticalWidth = root.querySelector('#border-vertical-width');
  const placementHelp = root.querySelector('#border-placement-help');
  let state = normalizeC64BorderSprites();
  let colorPlan = null;
  let available = true;
  let interlaced = false;

  function colorPicker(id, value, change) {
    const label = root.querySelector(`#${id}-value`);
    const updateLabel = index => {
      const color = palette.find(color => color.index === index);
      label.textContent = `${color.index} · ${color.name} · ${color.hex}`;
    };
    const picker = C64ConverterControls.createPalettePicker({
      container: root.querySelector(`#${id}-palette`), name: id, palette, value,
      onChange(color) {
        change(color.index);
        updateLabel(color.index);
        onChange?.(false);
      }
    });
    return {
      setValue(index) { picker.setValue(index); updateLabel(index); },
      refreshPalette() { picker.refreshPalette(); updateLabel(picker.getValue()); },
      setEnabled: picker.setEnabled
    };
  }

  const groups = ['vertical', 'sides'].map(key => {
    const enabled = root.querySelector(`#border-${key}-enabled`);
    const mode = root.querySelector(`#border-${key}-mode`);
    const colors = root.querySelector(`#border-${key}-colors`);
    const picker = colorPicker(`border-${key}-color`, state[key].colorIndex,
      value => { state[key].colorIndex = value; });
    enabled.addEventListener('change', () => {
      state[key].enabled = enabled.checked;
      render();
      onChange?.(true);
    });
    mode.addEventListener('change', () => {
      state[key].mode = mode.value;
      render();
      onChange?.(false);
    });
    return { key, enabled, mode, colors, picker };
  });
  const multicolors = [0, 1].map(index => colorPicker(`border-multi-${index + 1}`,
    state.multicolorIndices[index], value => { state.multicolorIndices[index] = value; }));
  verticalWidth.addEventListener('change', () => {
    state = normalizeC64BorderSprites({ ...state, vertical: { ...state.vertical,
      xExpanded: verticalWidth.value !== 'normal' } });
    colorPlan = null;
    render();
    onChange?.(false);
  });
  optimizeColors.addEventListener('change', () => {
    state = normalizeC64BorderSprites({ ...state, optimizeColors: optimizeColors.checked });
    colorPlan = null;
    render();
    onChange?.(false);
  });

  function render() {
    const anyEnabled = state.vertical.enabled || state.sides.enabled;
    const hasMulticolor = groups.some(({ key }) => state[key].enabled && state[key].mode === 'multicolor');
    const automatic = state.optimizeColors === true;
    optimizeColors.checked = automatic;
    optimizeColors.disabled = !available || !anyEnabled;
    fieldset.disabled = !available;
    verticalWidth.value = state.vertical.xExpanded === false ? 'normal' : 'expanded';
    verticalWidth.disabled = !available || !state.vertical.enabled;
    placementHelp.hidden = !available || !state.vertical.enabled || state.vertical.xExpanded !== false;
    root.setAttribute('aria-disabled', String(!available));
    for (const { key, enabled, mode, colors, picker } of groups) {
      enabled.checked = state[key].enabled;
      enabled.disabled = !available;
      mode.value = state[key].mode;
      mode.disabled = !available || !state[key].enabled;
      colors.hidden = !state[key].enabled || automatic;
      picker.setValue(state[key].colorIndex);
      picker.setEnabled(available && state[key].enabled && !automatic);
    }
    sharedColors.hidden = !anyEnabled;
    multicolorSettings.hidden = !hasMulticolor;
    multicolors.forEach((picker, index) => {
      picker.setValue(automatic && colorPlan ? colorPlan.multicolorIndices[index] : state.multicolorIndices[index]);
      picker.setEnabled(available && hasMulticolor && !automatic);
    });
    const layout = getC64BorderLayout(state);
    interlaceHelp.hidden = !available || !anyEnabled || !interlaced;
    summary.textContent = !available ? 'Unavailable for this graphics format.'
      : `${layout.width} × ${layout.height} display pixels${anyEnabled ? ' · borders included' : ' · borders off'}${anyEnabled && interlaced ? ' · 2 interlaced fields' : ''}`;
  }

  render();
  return {
    getState: () => normalizeC64BorderSprites(state),
    setState(value) { state = normalizeC64BorderSprites(value); colorPlan = null; render(); },
    setOptimizationPlan(value) { colorPlan = value; render(); },
    setEnabled(value) { available = Boolean(value); render(); },
    setInterlaced(value) { interlaced = Boolean(value); render(); },
    refreshPalette() {
      [...groups.map(group => group.picker), ...multicolors]
        .forEach(picker => picker.refreshPalette());
    }
  };
}

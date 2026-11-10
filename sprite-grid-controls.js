/** Shared sprite registers and per-cell colors for a grid of up to eight VIC sprites. */
function createC64SpriteGridControls({ root, palette, onChange }) {
  const grid = root.querySelector('#sprite-grid-size');
  const selected = root.querySelector('#sprite-grid-selected');
  const overlaySettings = root.querySelector('#sprite-grid-overlay-settings');
  let overlay = false;
  let state = {
    columns: 1, rows: 1, multicolorIndices: [5, 7],
    spriteColorIndices: Array(8).fill(14), overlayColorIndices: Array(8).fill(1)
  };
  let selectedIndex = 0;

  function colorPicker(id, value, change) {
    const label = root.querySelector(`#${id}-value`);
    const updateLabel = index => {
      const color = palette[index];
      label.textContent = `${color.index} · ${color.name} · ${color.hex}`;
    };
    const picker = C64ConverterControls.createPalettePicker({
      container: root.querySelector(`#${id}-palette`), name: id, palette, value,
      onChange(color) { updateLabel(color.index); change(color.index); onChange(false); }
    });
    return {
      setValue(index) { picker.setValue(index); updateLabel(index); },
      refreshPalette: picker.refreshPalette,
      setEnabled: picker.setEnabled
    };
  }

  const shared = [0, 1].map(slot => colorPicker(`sprite-grid-multi-${slot + 1}`,
    state.multicolorIndices[slot], index => { state.multicolorIndices[slot] = index; }));
  const individual = colorPicker('sprite-grid-color', state.spriteColorIndices[0],
    index => { state.spriteColorIndices[selectedIndex] = index; });
  const hires = colorPicker('sprite-grid-overlay', state.overlayColorIndices[0],
    index => { state.overlayColorIndices[selectedIndex] = index; });

  function renderColors() {
    shared.forEach((picker, slot) => picker.setValue(state.multicolorIndices[slot]));
    individual.setValue(state.spriteColorIndices[selectedIndex]);
    hires.setValue(state.overlayColorIndices[selectedIndex]);
  }

  function render() {
    const maxCells = overlay ? 4 : 8;
    grid.replaceChildren();
    for (let columns = 1; columns <= maxCells; columns += 1) {
      for (let rows = 1; columns * rows <= maxCells; rows += 1) {
        const option = document.createElement('option');
        option.value = `${columns}x${rows}`;
        option.textContent = `${columns} × ${rows}`;
        grid.append(option);
      }
    }
    grid.value = `${state.columns}x${state.rows}`;
    const cells = state.columns * state.rows;
    selectedIndex = Math.min(selectedIndex, cells - 1);
    selected.replaceChildren();
    for (let index = 0; index < cells; index += 1) {
      const option = document.createElement('option');
      option.value = String(index);
      option.textContent = `Sprite ${index + 1} · column ${index % state.columns + 1}, row ${Math.floor(index / state.columns) + 1}`;
      selected.append(option);
    }
    selected.value = String(selectedIndex);
    overlaySettings.hidden = !overlay;
    hires.setEnabled(overlay && !root.hidden);
    root.querySelector('#sprite-grid-summary').textContent =
      `${cells} multicolor${overlay ? ` + ${cells} hires` : ''} · ${cells * (overlay ? 2 : 1)} / 8 sprites · ${state.columns * 24} × ${state.rows * 21} pixels`;
    renderColors();
  }

  grid.addEventListener('change', () => {
    [state.columns, state.rows] = grid.value.split('x').map(Number);
    render();
    onChange(true);
  });
  selected.addEventListener('change', () => {
    selectedIndex = Number(selected.value);
    renderColors();
  });
  render();
  return {
    refreshPalette() {
      [...shared, individual, hires].forEach(picker => picker.refreshPalette());
      renderColors();
    },
    getState: () => ({ ...state, multicolorIndices: [...state.multicolorIndices],
      spriteColorIndices: [...state.spriteColorIndices], overlayColorIndices: [...state.overlayColorIndices] }),
    setState(value) {
      state = value ? { ...value, multicolorIndices: [...value.multicolorIndices],
        spriteColorIndices: [...value.spriteColorIndices], overlayColorIndices: [...value.overlayColorIndices] }
        : { columns: 1, rows: 1, multicolorIndices: [5, 7],
          spriteColorIndices: Array(8).fill(14), overlayColorIndices: Array(8).fill(1) };
      render();
    },
    setOverlay(value) {
      overlay = Boolean(value);
      if (overlay && state.columns * state.rows > 4) {
        state.columns = 2;
        state.rows = 2;
      }
      render();
    },
    setVisible(visible) {
      root.hidden = !visible;
      grid.disabled = !visible;
      selected.disabled = !visible;
      [...shared, individual].forEach(picker => picker.setEnabled(visible));
      hires.setEnabled(visible && overlay);
    }
  };
}

/** Shared character-mode colors; foreground color and resolution are fitted per screen cell. */
function createC64CharsetControls({ root, palette, onChange }) {
  let indices = [5, 7];
  const pickers = indices.map((value, slot) => {
    const id = `charset-multi-${slot + 1}`;
    const label = root.querySelector(`#${id}-value`);
    const updateLabel = index => {
      const color = palette[index];
      label.textContent = `${color.index} · ${color.name} · ${color.hex}`;
    };
    const picker = C64ConverterControls.createPalettePicker({
      container: root.querySelector(`#${id}-palette`), name: id, palette, value,
      onChange(color) { indices[slot] = color.index; updateLabel(color.index); onChange(); }
    });
    updateLabel(value);
    return { ...picker, updateLabel };
  });
  return {
    getState: () => [...indices],
    setState(value = [5, 7]) {
      indices = [...value];
      pickers.forEach((picker, slot) => {
        picker.setValue(indices[slot]);
        picker.updateLabel(indices[slot]);
      });
    },
    setVisible(visible) {
      root.hidden = !visible;
      pickers.forEach(picker => picker.setEnabled(visible));
    },
    setResult(result) {
      root.querySelector('#charset-summary').textContent = result
        ? `${result.characterCount} / 256 patterns · ${result.approximatedCellCount
          ? `${result.approximatedCellCount} cells use approximate patterns` : 'all cells retain their fitted patterns'}`
        : 'Up to 256 unique patterns for 40 × 25 cells.';
    }
  };
}

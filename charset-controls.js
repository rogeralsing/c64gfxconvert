/** Shared character-mode colors; foreground color and resolution are fitted per screen cell. */
function createC64CharsetControls({ root, palette, onChange }) {
  let indices = [5, 7];
  const similarity = root.querySelector('#charset-similarity');
  const similarityValue = root.querySelector('#charset-similarity-value');
  function updateSimilarityLabel() {
    similarityValue.value = `${similarity.value}%`;
    similarity.setAttribute('aria-valuetext', `${similarity.value}% tile similarity`);
  }
  similarity.addEventListener('input', updateSimilarityLabel);
  similarity.addEventListener('change', onChange);
  updateSimilarityLabel();
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
    getSimilarityThreshold: () => similarity.valueAsNumber,
    setSimilarityThreshold(value = 35) {
      similarity.value = String(value);
      updateSimilarityLabel();
    },
    setState(value = [5, 7]) {
      indices = [...value];
      pickers.forEach((picker, slot) => {
        picker.setValue(indices[slot]);
        picker.updateLabel(indices[slot]);
      });
    },
    setVisible(visible) {
      root.hidden = !visible;
      similarity.disabled = !visible;
      pickers.forEach(picker => picker.setEnabled(visible));
    },
    setResult(result) {
      root.querySelector('#charset-summary').textContent = result
        ? `${result.characterCount} / 256 patterns${result.unrestrictedCharacterCount > result.characterCount
          ? ` · reduced from ${result.unrestrictedCharacterCount}` : ''}${result.approximatedCellCount
          ? ` · ${result.approximatedCellCount} cells approximated` : ''}`
        : 'Up to 256 unique patterns for 40 × 25 cells.';
      const hires = result?.colorRam.reduce((count, value) => count + (value < 8 ? 1 : 0), 0);
      root.querySelector('#charset-mode-counts').textContent = result
        ? `${hires} hires · ${1000 - hires} multicolor cells` : 'Color and resolution are fitted per cell.';
    }
  };
}

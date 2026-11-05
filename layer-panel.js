/** Compact layer stack chrome; the converter owns selection and image processing. */
function createC64LayerPanel({ root, stack, onSelect, onAction, onRename }) {
  const list = root.querySelector('#layer-list');
  const document = root.ownerDocument;
  const icon = (name, size = 16) => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', size);
    svg.setAttribute('height', size);
    svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = `<use href="#icon-${name}"/>`;
    return svg;
  };
  for (const button of root.querySelectorAll('[data-layer-action]')) {
    button.addEventListener('click', () => onAction(button.dataset.layerAction));
  }
  function render() {
    list.replaceChildren();
    const selected = stack.active();
    root.querySelector('#layer-count').textContent = stack.layers.length;
    for (const layer of [...stack.layers].reverse()) {
      const row = document.createElement('div');
      row.className = `layer-row${layer.id === selected.id ? ' is-selected' : ''}${layer.visible ? '' : ' is-hidden'}`;
      row.dataset.layerId = layer.id;
      row.setAttribute('role', 'listitem');
      const visibility = document.createElement('button');
      visibility.type = 'button';
      visibility.className = 'layer-visibility';
      visibility.setAttribute('aria-label', `Show ${layer.name}`);
      visibility.setAttribute('aria-pressed', String(layer.visible));
      visibility.title = layer.visible ? 'Hide layer' : 'Show layer';
      visibility.append(icon(layer.visible ? 'eye' : 'eye-off'));
      visibility.addEventListener('click', () => onAction('visibility', layer.id));
      const select = document.createElement('button');
      select.type = 'button';
      select.className = 'layer-select';
      select.setAttribute('aria-pressed', String(layer.id === selected.id));
      select.setAttribute('aria-label', `Select ${layer.name}`);
      const thumbnail = document.createElement('canvas');
      thumbnail.width = 64;
      thumbnail.height = 40;
      thumbnail.className = 'layer-thumbnail';
      thumbnail.setAttribute('aria-hidden', 'true');
      if (layer.cache?.source) {
        const source = layer.cache.source;
        const buffer = document.createElement('canvas');
        buffer.width = source.width;
        buffer.height = source.height;
        buffer.getContext('2d').putImageData(source, 0, 0);
        thumbnail.getContext('2d').drawImage(buffer, 0, 0, 64, 40);
      } else if (layer.image) {
        const ratio = Math.min(64 / layer.image.naturalWidth, 40 / layer.image.naturalHeight);
        const width = layer.image.naturalWidth * ratio;
        const height = layer.image.naturalHeight * ratio;
        thumbnail.getContext('2d').drawImage(layer.image, (64 - width) / 2, (40 - height) / 2, width, height);
      }
      const label = document.createElement('span');
      label.textContent = layer.name;
      select.append(thumbnail, label);
      select.addEventListener('click', () => onSelect(layer.id));
      const rename = () => {
        const name = document.createElement('input');
        name.className = 'layer-rename';
        name.value = layer.name;
        name.setAttribute('aria-label', 'Layer name');
        let cancelled = false;
        name.addEventListener('keydown', event => {
          if (event.key !== 'Enter' && event.key !== 'Escape') return;
          event.preventDefault();
          cancelled = event.key === 'Escape';
          name.blur();
        });
        name.addEventListener('blur', () => {
          if (!cancelled && name.value.trim()) onRename(layer.id, name.value.trim());
          render();
        }, { once: true });
        select.replaceWith(name);
        name.focus({ preventScroll: true });
        name.select();
      };
      select.addEventListener('dblclick', rename);
      select.addEventListener('keydown', event => {
        if (event.key !== 'F2') return;
        event.preventDefault();
        rename();
      });
      row.append(visibility, select);
      list.append(row);
    }
    const index = stack.layers.indexOf(selected);
    root.querySelector('[data-layer-action="up"]').disabled = index === stack.layers.length - 1;
    root.querySelector('[data-layer-action="down"]').disabled = index === 0;
    root.querySelector('[data-layer-action="remove"]').disabled = stack.layers.length === 1;
  }
  render();
  return { render };
}

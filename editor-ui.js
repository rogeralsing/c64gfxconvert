/** Workspace chrome. Image processing remains in the converter controllers. */
(() => {
  const imageInput = document.getElementById('image-input');
  for (const button of document.querySelectorAll('[data-open-image]')) {
    button.addEventListener('click', () => imageInput.click());
  }

  for (const button of document.querySelectorAll('[data-inspector-panel]')) {
    button.addEventListener('click', () => {
      const panel = document.getElementById(button.dataset.inspectorPanel);
      panel.open = true;
      const sidebar = panel.closest('.config-sidebar');
      const top = panel.getBoundingClientRect().top - sidebar.getBoundingClientRect().top +
        sidebar.scrollTop - sidebar.querySelector('.inspector-heading').offsetHeight;
      if (getComputedStyle(sidebar).overflowY === 'auto') sidebar.scrollTo({ top });
      else panel.scrollIntoView({ block: 'start' });
      panel.querySelector('summary').focus({ preventScroll: true });
    });
  }
  document.getElementById('tool-reset-framing').addEventListener('click', () => {
    document.getElementById('reset-framing').click();
  });
  document.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === 'o') {
      event.preventDefault();
      imageInput.click();
    }
  });
  const sourceError = document.getElementById('error');
  new MutationObserver(() => {
    if (!sourceError.hidden) document.querySelector('[data-inspector-panel="source-settings"]').click();
  }).observe(sourceError, { attributes: true, attributeFilter: ['hidden'] });

  const screen = document.querySelector('.screen');
  const scale = document.getElementById('view-scale');
  const filename = document.getElementById('filename');
  const documentName = document.getElementById('document-name');
  const syncScale = () => {
    scale.textContent = filename.textContent ? `${Math.round(screen.getBoundingClientRect().width / 320 * 100)}%` : 'Fit';
  };
  const syncDocumentName = () => {
    documentName.textContent = filename.textContent || 'Untitled';
    documentName.title = documentName.textContent;
    document.getElementById('tool-reset-framing').disabled = !filename.textContent;
    syncScale();
  };
  new MutationObserver(syncDocumentName).observe(filename, { childList: true });
  syncDocumentName();

  new ResizeObserver(syncScale).observe(screen);

  const reference = document.getElementById('palette-reference');
  const swatches = reference.querySelector('.palette-reference-swatches');
  for (const color of C64_PALETTE) {
    const swatch = document.createElement('span');
    swatch.className = 'palette-reference-swatch';
    swatch.style.backgroundColor = color.hex;
    swatch.title = `${color.index} · ${color.name} · ${color.hex}`;
    swatch.setAttribute('role', 'listitem');
    swatch.setAttribute('aria-label', swatch.title);
    swatches.append(swatch);
  }
  const syncPaletteReference = () => {
    reference.hidden = !document.getElementById('background-settings').hidden ||
      !document.getElementById('sprite-settings').hidden || !document.getElementById('virtual-palette').hidden;
  };
  for (const id of ['graphics-mode-options', 'virtual-colors']) {
    document.getElementById(id).addEventListener('change', syncPaletteReference);
  }
  syncPaletteReference();
})();

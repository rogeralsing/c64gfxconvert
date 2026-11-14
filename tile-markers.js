/** Screen annotations stay separate from the image pixels used for conversion and export. */
function createC64TileMarkerEditor({ canvas, overlay, stack, getDisplaySize, onChange }) {
  const columns = 40;
  const rows = 25;
  const tileSize = 8;
  let stroke = null;

  function render() {
    const { width, height } = getDisplaySize();
    if (overlay.width !== width) overlay.width = width;
    if (overlay.height !== height) overlay.height = height;
    const context = overlay.getContext('2d');
    context.clearRect(0, 0, width, height);
    const layers = stack.layers.filter(layer => layer.type === 'tile-markers' && layer.visible);
    overlay.hidden = layers.length === 0;
    context.save();
    context.globalAlpha = 0.4;
    for (const layer of layers) {
      context.fillStyle = layer.markers.color;
      layer.markers.tiles.forEach((enabled, index) => {
        if (enabled) context.fillRect(index % columns * tileSize, Math.floor(index / columns) * tileSize,
          tileSize, tileSize);
      });
    }
    context.restore();
  }

  function cellAt(event) {
    const bounds = canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height || event.clientX < bounds.left || event.clientY < bounds.top ||
        event.clientX >= bounds.right || event.clientY >= bounds.bottom) return null;
    const { width, height } = getDisplaySize();
    const x = Math.floor((event.clientX - bounds.left) * width / bounds.width / tileSize);
    const y = Math.floor((event.clientY - bounds.top) * height / bounds.height / tileSize);
    return x < columns && y < rows ? { x, y } : null;
  }

  function finish(event) {
    if (!stroke || event && event.pointerId !== stroke.pointerId) return;
    const pointerId = stroke.pointerId;
    stroke = null;
    if (canvas.hasPointerCapture(pointerId)) canvas.releasePointerCapture(pointerId);
  }

  function paint(cell) {
    let changed = false;
    const from = stroke.lastCell || cell;
    let x = from.x;
    let y = from.y;
    const dx = Math.abs(cell.x - x);
    const dy = -Math.abs(cell.y - y);
    const stepX = x < cell.x ? 1 : -1;
    const stepY = y < cell.y ? 1 : -1;
    let error = dx + dy;
    while (true) {
      const index = y * columns + x;
      if (stroke.layer.markers.tiles[index] !== stroke.value) {
        stroke.layer.markers.tiles[index] = stroke.value;
        changed = true;
      }
      if (x === cell.x && y === cell.y) break;
      const twiceError = 2 * error;
      if (twiceError >= dy) { error += dy; x += stepX; }
      if (twiceError <= dx) { error += dx; y += stepY; }
    }
    stroke.lastCell = cell;
    if (changed) onChange(stroke.layer);
  }

  canvas.addEventListener('pointerdown', event => {
    const layer = stack.active();
    if (layer.type !== 'tile-markers' || !layer.visible || stroke || event.button !== 0 ||
        event.isPrimary === false) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const cell = cellAt(event);
    if (!cell) return;
    stroke = { layer, pointerId: event.pointerId, lastCell: null,
      value: layer.markers.tiles[cell.y * columns + cell.x] ? 0 : 1 };
    canvas.setPointerCapture(event.pointerId);
    paint(cell);
  });
  canvas.addEventListener('pointermove', event => {
    if (!stroke || event.pointerId !== stroke.pointerId) return;
    if (stack.active() !== stroke.layer || !stroke.layer.visible || !stack.layers.includes(stroke.layer)) {
      finish(event);
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    const cell = cellAt(event);
    if (cell) paint(cell);
    else stroke.lastCell = null;
  });
  for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) {
    canvas.addEventListener(event, finish);
  }
  return { render, finish };
}

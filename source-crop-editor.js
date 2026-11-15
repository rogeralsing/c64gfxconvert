/** Edit a source-space crop without changing the original image or the layer until Apply. */
function createSourceCropEditor({ dialog, onApply }) {
  const document = dialog.ownerDocument;
  const view = document.defaultView;
  dialog.classList.add('source-crop-dialog');
  dialog.setAttribute('aria-labelledby', 'source-crop-title');
  dialog.innerHTML = `
    <header class="source-crop-heading">
      <div><h2 id="source-crop-title">Crop source image</h2><p id="source-crop-name"></p></div>
      <span id="source-crop-size"></span>
    </header>
    <div class="source-crop-toolbar">
      <label for="source-crop-shape">Shape <select id="source-crop-shape"><option value="rectangle">Rectangle</option><option value="polygon">Polygon</option></select></label>
      <label for="source-crop-x">X <input id="source-crop-x" type="number" min="0" step="1"></label>
      <label for="source-crop-y">Y <input id="source-crop-y" type="number" min="0" step="1"></label>
      <button id="source-crop-delete" class="framing-reset" type="button">Remove point</button>
      <span id="source-crop-status" role="status" aria-live="polite"></span>
      <button id="source-crop-reset" class="framing-reset" type="button">Reset crop</button>
    </div>
    <div class="source-crop-stage"><canvas id="source-crop-canvas" tabindex="0" role="group" aria-roledescription="crop editor" aria-describedby="source-crop-help"></canvas></div>
    <p id="source-crop-help" class="source-crop-help">Drag handles to crop. Click an edge to add a polygon point. Delete removes a point. Arrow keys move; Shift moves 10 pixels.</p>
    <p id="source-crop-error" class="source-crop-error" role="alert" hidden></p>
    <footer class="source-crop-actions"><button id="source-crop-cancel" class="open-button" type="button">Cancel</button><button id="source-crop-apply" class="afli-save" type="button">Apply crop</button></footer>`;
  const canvas = dialog.querySelector('#source-crop-canvas');
  const stage = dialog.querySelector('.source-crop-stage');
  const context = canvas.getContext('2d');
  const shape = dialog.querySelector('#source-crop-shape');
  const inputX = dialog.querySelector('#source-crop-x');
  const inputY = dialog.querySelector('#source-crop-y');
  const remove = dialog.querySelector('#source-crop-delete');
  const apply = dialog.querySelector('#source-crop-apply');
  const error = dialog.querySelector('#source-crop-error');
  const status = dialog.querySelector('#source-crop-status');
  const fullRectangle = () => ({ mode: 'rectangle', points: [
    { x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }
  ] });
  let image = null;
  let draft = fullRectangle();
  let selected = 0;
  let drag = null;
  let sourceWidth = 1;
  let sourceHeight = 1;

  function geometry() {
    const width = stage.clientWidth;
    const height = stage.clientHeight;
    const scale = Math.max(0, Math.min((width - 36) / sourceWidth, (height - 36) / sourceHeight));
    return { width, height, left: (width - sourceWidth * scale) / 2,
      top: (height - sourceHeight * scale) / 2, imageWidth: sourceWidth * scale,
      imageHeight: sourceHeight * scale };
  }

  function draw() {
    if (!image || !dialog.open) return;
    const bounds = geometry();
    const density = view.devicePixelRatio || 1;
    const width = Math.round(bounds.width * density);
    const height = Math.round(bounds.height * density);
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    context.setTransform(density, 0, 0, density, 0, 0);
    context.clearRect(0, 0, bounds.width, bounds.height);
    const screen = point => ({ x: bounds.left + point.x * bounds.imageWidth,
      y: bounds.top + point.y * bounds.imageHeight });
    const points = draft.points.map(screen);
    context.drawImage(image, bounds.left, bounds.top, bounds.imageWidth, bounds.imageHeight);
    context.beginPath();
    context.rect(bounds.left, bounds.top, bounds.imageWidth, bounds.imageHeight);
    context.moveTo(points[0].x, points[0].y);
    for (const point of points.slice(1)) context.lineTo(point.x, point.y);
    context.closePath();
    context.fillStyle = '#000a';
    context.fill('evenodd');
    context.beginPath();
    context.moveTo(points[0].x, points[0].y);
    for (const point of points.slice(1)) context.lineTo(point.x, point.y);
    context.closePath();
    context.strokeStyle = '#000c';
    context.lineWidth = 4;
    context.stroke();
    const accent = view.getComputedStyle(dialog).getPropertyValue('--accent').trim() || '#60a5fa';
    context.strokeStyle = accent;
    context.lineWidth = 2;
    context.stroke();
    points.forEach((point, index) => {
      context.beginPath();
      context.arc(point.x, point.y, 6, 0, Math.PI * 2);
      context.fillStyle = index === selected ? accent : '#222';
      context.fill();
      context.strokeStyle = index === selected ? '#fff' : accent;
      context.lineWidth = 2;
      context.stroke();
    });
  }

  function update() {
    const point = draft.points[selected];
    shape.value = draft.mode;
    inputX.max = String(sourceWidth);
    inputY.max = String(sourceHeight);
    inputX.value = String(Math.round(point.x * sourceWidth));
    inputY.value = String(Math.round(point.y * sourceHeight));
    remove.disabled = draft.points.length <= 3;
    status.textContent = `Point ${selected + 1} of ${draft.points.length}`;
    canvas.setAttribute('aria-label', `${draft.mode === 'rectangle' ? 'Rectangle' : 'Polygon'} crop, ` +
      `point ${selected + 1} of ${draft.points.length}, X ${inputX.value}, Y ${inputY.value}. ` +
      'Arrow keys move; Page Up and Page Down select; Insert adds a point; Delete removes a point.');
    try {
      cloneSourceCrop(draft);
      error.hidden = true;
      error.textContent = '';
      apply.disabled = false;
    } catch (cause) {
      error.textContent = `Adjust the crop: ${cause.message}`;
      error.hidden = false;
      apply.disabled = true;
    }
    draw();
  }

  function finish(event) {
    if (!drag || event && event.pointerId !== drag.pointerId) return;
    const pointerId = drag.pointerId;
    drag = null;
    canvas.classList.remove('is-dragging');
    if (canvas.hasPointerCapture(pointerId)) canvas.releasePointerCapture(pointerId);
  }

  function movePoint(x, y) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    x = Math.max(0, Math.min(1, Math.round(x * sourceWidth) / sourceWidth));
    y = Math.max(0, Math.min(1, Math.round(y * sourceHeight) / sourceHeight));
    if (draft.mode === 'rectangle') {
      const left = selected === 0 || selected === 3;
      const top = selected < 2;
      const opposite = draft.points[(selected + 2) % 4];
      x = left ? Math.min(x, opposite.x - 1 / sourceWidth) : Math.max(x, opposite.x + 1 / sourceWidth);
      y = top ? Math.min(y, opposite.y - 1 / sourceHeight) : Math.max(y, opposite.y + 1 / sourceHeight);
      for (const index of left ? [0, 3] : [1, 2]) draft.points[index].x = x;
      for (const index of top ? [0, 1] : [2, 3]) draft.points[index].y = y;
    } else {
      draft.points[selected] = { x, y };
    }
    update();
  }

  function addPoint(edge, point) {
    if (draft.points.length >= 256) return;
    draft.mode = 'polygon';
    selected = edge + 1;
    draft.points.splice(selected, 0, { x: point.x, y: point.y });
    update();
  }

  function deletePoint() {
    if (draft.points.length <= 3) return;
    draft.mode = 'polygon';
    draft.points.splice(selected, 1);
    selected = Math.min(selected, draft.points.length - 1);
    update();
  }

  function position(event) {
    const rect = canvas.getBoundingClientRect();
    const bounds = geometry();
    const x = (event.clientX - rect.left) * bounds.width / rect.width;
    const y = (event.clientY - rect.top) * bounds.height / rect.height;
    return { x, y, sourceX: (x - bounds.left) / bounds.imageWidth,
      sourceY: (y - bounds.top) / bounds.imageHeight };
  }

  function hit(position) {
    const bounds = geometry();
    const points = draft.points.map(point => ({ x: bounds.left + point.x * bounds.imageWidth,
      y: bounds.top + point.y * bounds.imageHeight }));
    let node = -1;
    let distance = 11 ** 2;
    points.forEach((point, index) => {
      const next = (point.x - position.x) ** 2 + (point.y - position.y) ** 2;
      if (next < distance) { node = index; distance = next; }
    });
    if (node >= 0) return { node };
    let edge = -1;
    let projected = null;
    distance = 8 ** 2;
    points.forEach((first, index) => {
      const second = points[(index + 1) % points.length];
      const dx = second.x - first.x;
      const dy = second.y - first.y;
      const length = dx * dx + dy * dy;
      if (length === 0) return;
      const ratio = Math.max(0, Math.min(1, ((position.x - first.x) * dx + (position.y - first.y) * dy) / length));
      const x = first.x + ratio * dx;
      const y = first.y + ratio * dy;
      const next = (position.x - x) ** 2 + (position.y - y) ** 2;
      if (next < distance) {
        distance = next;
        edge = index;
        projected = { x: (x - bounds.left) / bounds.imageWidth, y: (y - bounds.top) / bounds.imageHeight };
      }
    });
    return { node, edge, point: projected };
  }

  canvas.addEventListener('pointerdown', event => {
    if (!image || drag || event.button !== 0 || event.isPrimary === false) return;
    const target = hit(position(event));
    if (target.node < 0 && (target.edge < 0 || draft.points.length >= 256)) return;
    event.preventDefault();
    canvas.focus({ preventScroll: true });
    if (target.node >= 0) { selected = target.node; update(); }
    else addPoint(target.edge, target.point);
    drag = { pointerId: event.pointerId };
    canvas.classList.add('is-dragging');
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove', event => {
    if (!image) return;
    const target = position(event);
    if (!drag) {
      const match = hit(target);
      canvas.style.cursor = match.node >= 0 ? 'grab' : match.edge >= 0 ? 'crosshair' : 'default';
      return;
    }
    if (event.pointerId !== drag.pointerId) return;
    event.preventDefault();
    movePoint(target.sourceX, target.sourceY);
  });
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) canvas.addEventListener(type, finish);
  canvas.addEventListener('dblclick', event => {
    if (!image) return;
    const target = hit(position(event));
    if (target.node < 0) return;
    event.preventDefault();
    selected = target.node;
    deletePoint();
  });
  canvas.addEventListener('keydown', event => {
    if (!image) return;
    const point = draft.points[selected];
    const step = event.shiftKey ? 10 : 1;
    if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      deletePoint();
    } else if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
      event.preventDefault();
      movePoint(point.x + (event.key === 'ArrowRight' ? step : event.key === 'ArrowLeft' ? -step : 0) / sourceWidth,
        point.y + (event.key === 'ArrowDown' ? step : event.key === 'ArrowUp' ? -step : 0) / sourceHeight);
    } else if (['PageUp', 'PageDown', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      selected = event.key === 'Home' ? 0 : event.key === 'End' ? draft.points.length - 1
        : Math.max(0, Math.min(draft.points.length - 1, selected + (event.key === 'PageDown' ? 1 : -1)));
      update();
    } else if (event.key === 'Insert' || event.key === 'Enter') {
      event.preventDefault();
      const next = draft.points[(selected + 1) % draft.points.length];
      addPoint(selected, { x: (point.x + next.x) / 2, y: (point.y + next.y) / 2 });
    }
  });
  for (const [input, axis] of [[inputX, 'x'], [inputY, 'y']]) {
    input.addEventListener('input', () => {
      if (!Number.isFinite(input.valueAsNumber)) return;
      const point = draft.points[selected];
      movePoint(axis === 'x' ? input.valueAsNumber / sourceWidth : point.x,
        axis === 'y' ? input.valueAsNumber / sourceHeight : point.y);
    });
    input.addEventListener('change', update);
  }
  shape.addEventListener('change', () => {
    finish();
    if (shape.value === 'rectangle') {
      let left = Math.min(...draft.points.map(point => point.x));
      let right = Math.max(...draft.points.map(point => point.x));
      let top = Math.min(...draft.points.map(point => point.y));
      let bottom = Math.max(...draft.points.map(point => point.y));
      if (right - left < 1 / sourceWidth) {
        left = Math.min(left, 1 - 1 / sourceWidth);
        right = left + 1 / sourceWidth;
      }
      if (bottom - top < 1 / sourceHeight) {
        top = Math.min(top, 1 - 1 / sourceHeight);
        bottom = top + 1 / sourceHeight;
      }
      draft = { mode: 'rectangle', points: [
        { x: left, y: top }, { x: right, y: top }, { x: right, y: bottom }, { x: left, y: bottom }
      ] };
      selected = 0;
    } else draft.mode = 'polygon';
    update();
  });
  remove.addEventListener('click', deletePoint);
  dialog.querySelector('#source-crop-reset').addEventListener('click', () => {
    finish();
    draft = fullRectangle();
    selected = 0;
    update();
  });
  function close() {
    finish();
    if (dialog.open) dialog.close();
    image = null;
  }
  dialog.querySelector('#source-crop-cancel').addEventListener('click', close);
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  dialog.addEventListener('close', () => { if (!dialog.open) { finish(); image = null; } });
  apply.addEventListener('click', () => {
    if (apply.disabled || !image) return;
    const full = draft.mode === 'rectangle' && draft.points.every((point, index) => {
      const expected = fullRectangle().points[index];
      return point.x === expected.x && point.y === expected.y;
    });
    const crop = full ? null : cloneSourceCrop(draft);
    close();
    onApply?.(crop);
  });
  if (view.ResizeObserver) new view.ResizeObserver(draw).observe(stage);
  return {
    open({ image: source, crop = null, name = 'Image' }) {
      close();
      sourceWidth = source.naturalWidth || source.width;
      sourceHeight = source.naturalHeight || source.height;
      if (!sourceWidth || !sourceHeight) return;
      image = source;
      draft = cloneSourceCrop(crop) || fullRectangle();
      selected = 0;
      dialog.querySelector('#source-crop-name').textContent = name;
      dialog.querySelector('#source-crop-size').textContent = `${sourceWidth} × ${sourceHeight} source pixels`;
      dialog.showModal();
      update();
      canvas.focus({ preventScroll: true });
    },
    close
  };
}

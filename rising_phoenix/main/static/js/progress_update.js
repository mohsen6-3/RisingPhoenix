(function () {
  'use strict';

  var MAX_IMAGES = 5;

  // ── Shared editor DOM ─────────────────────────────────────────────────
  var editorModal      = document.getElementById('progress-image-editor-modal');
  var editorCloseBtn   = document.getElementById('progress-image-editor-close');
  var editorHost       = document.getElementById('progress-image-editor-host');
  var saveBtn          = document.getElementById('progress-editor-save');
  var cancelBtn        = document.getElementById('progress-editor-cancel');
  var undoBtn          = document.getElementById('progress-editor-undo');
  var clearAllBtn      = document.getElementById('progress-editor-clear-all');
  var modeDrawBtn      = document.getElementById('progress-editor-mode-draw');
  var modeHighlightBtn = document.getElementById('progress-editor-mode-highlight');
  var widthThinBtn     = document.getElementById('progress-editor-width-thin');
  var widthThickBtn    = document.getElementById('progress-editor-width-thick');
  var colorGroup       = document.getElementById('progress-editor-color-group');
  var widthGroup       = document.getElementById('progress-editor-width-group');

  if (!editorModal || !saveBtn || !cancelBtn) return;

  // ── Shared editor state ───────────────────────────────────────────────
  var editorCanvas    = null;
  var originalImage   = null;
  var strokes         = [];
  var currentStroke   = null;
  var isDragging      = false;
  var editorMode      = 'draw';
  var drawColor       = '#e53935';
  var drawWidth       = 3;
  var editorImageType = 'image/jpeg';
  var activeZone      = null;
  var activeItemId    = null;

  // ── Rendering ─────────────────────────────────────────────────────────
  function renderStroke(ctx, stroke) {
    if (stroke.type === 'draw') {
      if (stroke.points.length < 2) return;
      ctx.save();
      ctx.strokeStyle = stroke.color;
      ctx.lineWidth   = stroke.width;
      ctx.lineCap     = 'round';
      ctx.lineJoin    = 'round';
      ctx.beginPath();
      ctx.moveTo(stroke.points[0].x, stroke.points[0].y);
      for (var i = 1; i < stroke.points.length; i++) ctx.lineTo(stroke.points[i].x, stroke.points[i].y);
      ctx.stroke();
      ctx.restore();
    } else if (stroke.type === 'highlight') {
      var r = stroke.rect;
      if (!r || r.w < 2 || r.h < 2) return;
      ctx.save();
      ctx.globalAlpha = 0.38;
      ctx.fillStyle   = stroke.color;
      ctx.fillRect(r.x, r.y, r.w, r.h);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = stroke.color;
      ctx.lineWidth   = 1.5;
      ctx.strokeRect(r.x + 0.5, r.y + 0.5, r.w, r.h);
      ctx.restore();
    }
  }

  function drawEditorCanvas() {
    if (!editorCanvas || !originalImage) return;
    var ctx = editorCanvas.getContext('2d');
    ctx.clearRect(0, 0, editorCanvas.width, editorCanvas.height);
    ctx.drawImage(originalImage, 0, 0, editorCanvas.width, editorCanvas.height);
    strokes.forEach(function (s) { renderStroke(ctx, s); });
    if (currentStroke) renderStroke(ctx, currentStroke);
  }

  function setupEditorCanvas() {
    if (!originalImage || !editorCanvas) return;
    var maxW  = editorHost.clientWidth  || 600;
    var maxH  = editorHost.clientHeight || 400;
    var scale = Math.min(maxW / originalImage.naturalWidth, maxH / originalImage.naturalHeight, 1);
    editorCanvas.width  = Math.max(1, Math.round(originalImage.naturalWidth  * scale));
    editorCanvas.height = Math.max(1, Math.round(originalImage.naturalHeight * scale));
    strokes = [];
    drawEditorCanvas();
  }

  function getCanvasPoint(e) {
    var rect   = editorCanvas.getBoundingClientRect();
    var scaleX = editorCanvas.width  / rect.width;
    var scaleY = editorCanvas.height / rect.height;
    var src    = e.touches ? e.touches[0] : e;
    return { x: (src.clientX - rect.left) * scaleX, y: (src.clientY - rect.top) * scaleY };
  }

  function onPointerDown(e) {
    e.preventDefault();
    isDragging = true;
    var pt = getCanvasPoint(e);
    if (editorMode === 'draw') {
      currentStroke = { type: 'draw', color: drawColor, width: drawWidth, points: [pt] };
    } else {
      currentStroke = { type: 'highlight', color: drawColor, startPt: pt, rect: { x: pt.x, y: pt.y, w: 0, h: 0 } };
    }
  }

  function onPointerMove(e) {
    if (!isDragging || !currentStroke) return;
    e.preventDefault();
    var pt = getCanvasPoint(e);
    if (currentStroke.type === 'draw') {
      currentStroke.points.push(pt);
    } else {
      var sp = currentStroke.startPt;
      currentStroke.rect = { x: Math.min(pt.x, sp.x), y: Math.min(pt.y, sp.y), w: Math.abs(pt.x - sp.x), h: Math.abs(pt.y - sp.y) };
    }
    drawEditorCanvas();
  }

  function onPointerUp() {
    if (!isDragging || !currentStroke) return;
    isDragging = false;
    var skip = (currentStroke.type === 'draw' && currentStroke.points.length < 2) ||
               (currentStroke.type === 'highlight' && (currentStroke.rect.w < 5 || currentStroke.rect.h < 5));
    if (!skip) strokes.push(currentStroke);
    currentStroke = null;
    drawEditorCanvas();
  }

  function syncWidthGroupVisibility() {
    if (widthGroup) widthGroup.style.display = editorMode === 'draw' ? '' : 'none';
  }

  // ── Open / close editor ───────────────────────────────────────────────
  function openEditorForFile(file, zone, itemId) {
    var reader = new FileReader();
    reader.onload = function (ev) {
      activeZone      = zone;
      activeItemId    = itemId;
      editorImageType = file.type || 'image/jpeg';
      strokes         = [];
      currentStroke   = null;
      isDragging      = false;
      var img = new Image();
      img.onload = function () {
        originalImage = img;
        editorHost.innerHTML = '';
        editorCanvas = document.createElement('canvas');
        editorCanvas.style.cursor     = 'crosshair';
        editorCanvas.style.touchAction = 'none';
        editorHost.appendChild(editorCanvas);
        editorModal.hidden = false;
        requestAnimationFrame(function () {
          setupEditorCanvas();
          editorCanvas.addEventListener('mousedown',  onPointerDown);
          editorCanvas.addEventListener('mousemove',  onPointerMove);
          editorCanvas.addEventListener('mouseup',    onPointerUp);
          editorCanvas.addEventListener('mouseleave', onPointerUp);
          editorCanvas.addEventListener('touchstart', onPointerDown, { passive: false });
          editorCanvas.addEventListener('touchmove',  onPointerMove, { passive: false });
          editorCanvas.addEventListener('touchend',   onPointerUp);
        });
      };
      img.src = ev.target.result;
    };
    reader.readAsDataURL(file);
  }

  function closeEditor() {
    editorModal.hidden = true;
    activeZone         = null;
    activeItemId       = null;
    originalImage      = null;
    editorCanvas       = null;
    strokes            = [];
    currentStroke      = null;
    isDragging         = false;
    editorHost.innerHTML = '';
  }

  // ── Save edits ────────────────────────────────────────────────────────
  saveBtn.addEventListener('click', function () {
    if (!originalImage || !editorCanvas || !activeZone || activeItemId === null) return;

    var outCanvas  = document.createElement('canvas');
    outCanvas.width  = originalImage.naturalWidth;
    outCanvas.height = originalImage.naturalHeight;
    var outCtx = outCanvas.getContext('2d');
    outCtx.drawImage(originalImage, 0, 0);

    if (strokes.length) {
      var scaleX = originalImage.naturalWidth  / editorCanvas.width;
      var scaleY = originalImage.naturalHeight / editorCanvas.height;
      outCtx.scale(scaleX, scaleY);
      strokes.forEach(function (s) { renderStroke(outCtx, s); });
    }

    var mimeType = editorImageType && editorImageType.startsWith('image/') ? editorImageType : 'image/jpeg';
    outCanvas.toBlob(function (blob) {
      if (!blob) return;
      var ext        = mimeType === 'image/png' ? '.png' : (mimeType === 'image/webp' ? '.webp' : '.jpg');
      var targetZone = activeZone;
      var targetId   = activeItemId;
      closeEditor();
      targetZone.replaceItem(targetId, blob, mimeType, ext);
    }, mimeType, mimeType === 'image/png' ? 1 : 0.92);
  });

  // ── Upload zone factory ───────────────────────────────────────────────
  function createUploadZone(cfg) {
    var input = document.getElementById(cfg.inputId);
    var zone  = document.getElementById(cfg.zoneId);
    var grid  = document.getElementById(cfg.gridId);
    var badge = cfg.badgeId ? document.getElementById(cfg.badgeId) : null;
    var form  = document.getElementById(cfg.formId);
    if (!input || !zone || !grid || !form) return null;

    var items  = [];
    var nextId = 1;

    function fileKey(file) {
      return [file.name, file.size, file.lastModified].join('::');
    }

    function syncInput() {
      var dt = new DataTransfer();
      items.forEach(function (item) { dt.items.add(item.file); });
      input.files = dt.files;
    }

    function updateBadge() {
      if (!badge) return;
      if (!items.length) { badge.hidden = true; return; }
      badge.textContent = items.length + ' / ' + MAX_IMAGES + ' image' + (items.length !== 1 ? 's' : '') + ' added';
      badge.hidden      = false;
      badge.className   = 'img-count-badge' + (items.length >= MAX_IMAGES ? ' img-count-full' : '');
    }

    function renderPreviews() {
      grid.innerHTML = '';
      zone.classList.toggle('is-full', items.length >= MAX_IMAGES);
      if (!items.length) { grid.hidden = true; updateBadge(); return; }
      grid.hidden = false;
      updateBadge();

      items.forEach(function (item) {
        var reader = new FileReader();
        reader.onload = function (ev) {
          var wrap = document.createElement('div');
          wrap.className = 'img-preview-item';

          var leftCol = document.createElement('div');
          leftCol.className = 'img-preview-left';

          var img = document.createElement('img');
          img.src = ev.target.result;
          img.alt = item.file.name;

          var actionRow = document.createElement('div');
          actionRow.className = 'img-preview-actions';

          var editBtn = document.createElement('button');
          editBtn.type      = 'button';
          editBtn.className = 'img-preview-action';
          editBtn.textContent = 'Mark up';
          editBtn.addEventListener('click', function () { openEditorForFile(item.file, api, item.id); });

          var removeBtn = document.createElement('button');
          removeBtn.type      = 'button';
          removeBtn.className = 'img-preview-action img-preview-action-danger';
          removeBtn.textContent = 'Remove';
          removeBtn.addEventListener('click', function () {
            items = items.filter(function (i) { return i.id !== item.id; });
            syncInput();
            renderPreviews();
          });

          actionRow.appendChild(editBtn);
          actionRow.appendChild(removeBtn);
          leftCol.appendChild(img);
          leftCol.appendChild(actionRow);

          var rightCol = document.createElement('div');
          rightCol.className = 'img-preview-right';

          var name = document.createElement('p');
          name.className   = 'img-preview-name';
          name.textContent = item.file.name;

          var captionInput = document.createElement('textarea');
          captionInput.className   = 'img-preview-caption';
          captionInput.placeholder = 'Add a note about this image...';
          captionInput.maxLength   = 160;
          captionInput.value       = item.caption;
          captionInput.rows        = 3;

          var hiddenCaption = document.createElement('input');
          hiddenCaption.type  = 'hidden';
          hiddenCaption.name  = cfg.captionFieldName;
          hiddenCaption.value = item.caption;

          captionInput.addEventListener('input', function () {
            item.caption        = captionInput.value;
            hiddenCaption.value = item.caption;
          });

          rightCol.appendChild(name);
          rightCol.appendChild(captionInput);
          rightCol.appendChild(hiddenCaption);
          wrap.appendChild(leftCol);
          wrap.appendChild(rightCol);
          grid.appendChild(wrap);
        };
        reader.readAsDataURL(item.file);
      });
    }

    function addFiles(newFiles) {
      var existing = new Set(items.map(function (item) { return fileKey(item.file); }));
      var added = [];
      Array.from(newFiles).forEach(function (file) {
        if (items.length >= MAX_IMAGES) return;
        if (!file.type.startsWith('image/')) return;
        var key = fileKey(file);
        if (existing.has(key)) return;
        var item = { id: nextId++, file: file, caption: '' };
        items.push(item);
        added.push(item);
        existing.add(key);
      });
      syncInput();
      renderPreviews();
      return added;
    }

    var api = {
      addFiles: addFiles,
      replaceItem: function (itemId, blob, mimeType, ext) {
        var target = items.find(function (i) { return i.id === itemId; });
        if (!target) return;
        var origName = target.file.name;
        var oDot     = origName.lastIndexOf('.');
        var oBase    = oDot > 0 ? origName.slice(0, oDot) : origName;
        var newFile  = new File([blob], oBase + '-marked' + ext, { type: mimeType, lastModified: Date.now() });
        target.file  = newFile;
        syncInput();
        renderPreviews();
      },
    };

    input.addEventListener('change', function () {
      var selected = Array.from(this.files);
      this.value = '';
      addFiles(selected);
    });
    zone.addEventListener('dragover',  function (e) { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', function ()  { zone.classList.remove('drag-over'); });
    zone.addEventListener('drop', function (e) {
      e.preventDefault();
      zone.classList.remove('drag-over');
      addFiles(e.dataTransfer.files);
    });

    // Double-submit guard (handles multiple submit buttons via formaction)
    form.addEventListener('submit', function (e) {
      var clicked = e.submitter || form.querySelector('button[type="submit"]');
      if (!clicked) return;
      var origLabel = clicked.innerHTML;
      clicked.disabled  = true;
      clicked.innerHTML = 'Submitting...';
      setTimeout(function () {
        clicked.disabled  = false;
        clicked.innerHTML = origLabel;
      }, 10000);
    });

    return api;
  }

  // ── Instantiate zones ─────────────────────────────────────────────────
  var zones = {
    artisan: createUploadZone({
      inputId:          'id_artisan_images',
      zoneId:           'artisan-img-upload-zone',
      gridId:           'artisan-img-preview-grid',
      badgeId:          'artisan-img-count-badge',
      captionFieldName: 'image_captions',
      formId:           'artisan-form',
    }),
    requester: createUploadZone({
      inputId:          'id_requester_images',
      zoneId:           'requester-img-upload-zone',
      gridId:           'requester-img-preview-grid',
      badgeId:          'requester-img-count-badge',
      captionFieldName: 'image_captions',
      formId:           'requester-form',
    }),
  };

  // ── Include existing timeline images ──────────────────────────────────
  function mimeFromName(name) {
    var ext = (name.split('.').pop() || '').toLowerCase();
    return { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp', gif: 'image/gif' }[ext] || 'image/jpeg';
  }

  document.querySelectorAll('.progress-include-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var key        = btn.dataset.targetZone;
      var targetZone = zones[key];
      if (!targetZone) return;

      var url      = btn.dataset.src;
      var srcName  = url.split('/').pop().split('?')[0] || 'image.jpg';
      var origText = btn.textContent;

      btn.disabled    = true;
      btn.textContent = '…';

      fetch(url, { credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.blob();
        })
        .then(function (blob) {
          var type = (blob.type && blob.type.startsWith('image/')) ? blob.type : mimeFromName(srcName);
          var file = new File([blob], srcName, { type: type });
          var added = targetZone.addFiles([file]);
          btn.disabled    = false;
          btn.textContent = (added && added.length) ? '✓ Added' : origText;
          if (added && added.length) setTimeout(function () { btn.textContent = origText; }, 2000);
        })
        .catch(function () {
          btn.disabled    = false;
          btn.textContent = 'Failed';
          setTimeout(function () { btn.textContent = origText; }, 2000);
        });
    });
  });

  // ── Editor controls ───────────────────────────────────────────────────
  if (undoBtn)     undoBtn.addEventListener('click',     function () { strokes.pop(); drawEditorCanvas(); });
  if (clearAllBtn) clearAllBtn.addEventListener('click', function () { strokes = []; drawEditorCanvas(); });

  if (modeDrawBtn) {
    modeDrawBtn.addEventListener('click', function () {
      editorMode = 'draw';
      modeDrawBtn.classList.add('is-active');
      if (modeHighlightBtn) modeHighlightBtn.classList.remove('is-active');
      syncWidthGroupVisibility();
    });
  }
  if (modeHighlightBtn) {
    modeHighlightBtn.addEventListener('click', function () {
      editorMode = 'highlight';
      modeHighlightBtn.classList.add('is-active');
      if (modeDrawBtn) modeDrawBtn.classList.remove('is-active');
      syncWidthGroupVisibility();
    });
  }
  if (widthThinBtn) {
    widthThinBtn.addEventListener('click', function () {
      drawWidth = 3;
      widthThinBtn.classList.add('is-active');
      if (widthThickBtn) widthThickBtn.classList.remove('is-active');
    });
  }
  if (widthThickBtn) {
    widthThickBtn.addEventListener('click', function () {
      drawWidth = 7;
      widthThickBtn.classList.add('is-active');
      if (widthThinBtn) widthThinBtn.classList.remove('is-active');
    });
  }
  if (colorGroup) {
    colorGroup.addEventListener('click', function (e) {
      var swatch = e.target.closest('.editor-color-swatch');
      if (!swatch) return;
      drawColor = swatch.dataset.color;
      colorGroup.querySelectorAll('.editor-color-swatch').forEach(function (s) {
        s.classList.toggle('is-active', s === swatch);
      });
    });
  }

  cancelBtn.addEventListener('click', closeEditor);
  if (editorCloseBtn) editorCloseBtn.addEventListener('click', closeEditor);
  editorModal.addEventListener('click', function (e) { if (e.target === editorModal) closeEditor(); });
})();

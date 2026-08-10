// Lightweight canvas signature pad for the public quote-approval page.
// Draws with mouse or touch, writes a PNG data-URL into #signature_data on submit.
(function () {
  const canvas = document.getElementById('sigpad');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  let drawing = false;
  let hasInk = false;

  // Match the canvas backing store to its displayed size for crisp lines.
  function resize() {
    const ratio = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    // Preserve any existing drawing across a resize.
    const prev = hasInk ? canvas.toDataURL() : null;
    canvas.width = rect.width * ratio;
    canvas.height = rect.height * ratio;
    ctx.scale(ratio, ratio);
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = '#f9fafb';
    if (prev) {
      const img = new Image();
      img.onload = () => ctx.drawImage(img, 0, 0, rect.width, rect.height);
      img.src = prev;
    }
  }
  resize();
  window.addEventListener('resize', resize);

  function pos(e) {
    const rect = canvas.getBoundingClientRect();
    const src = e.touches ? e.touches[0] : e;
    return { x: src.clientX - rect.left, y: src.clientY - rect.top };
  }

  function start(e) {
    drawing = true;
    hasInk = true;
    const p = pos(e);
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    e.preventDefault();
  }
  function move(e) {
    if (!drawing) return;
    const p = pos(e);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    e.preventDefault();
  }
  function end() { drawing = false; }

  canvas.addEventListener('mousedown', start);
  canvas.addEventListener('mousemove', move);
  window.addEventListener('mouseup', end);
  canvas.addEventListener('touchstart', start, { passive: false });
  canvas.addEventListener('touchmove', move, { passive: false });
  canvas.addEventListener('touchend', end);

  const clearBtn = document.getElementById('sig-clear');
  if (clearBtn) {
    clearBtn.addEventListener('click', function () {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      hasInk = false;
    });
  }

  // Called from the form's onsubmit.
  window.prepareSignature = function () {
    if (!hasInk) {
      alert('Please sign in the box before approving.');
      return false;
    }
    document.getElementById('signature_data').value = canvas.toDataURL('image/png');
    return true;
  };
})();

(function () {
  // --- Thumbnail gallery ---
  const stage = document.getElementById('gallery-stage');
  const mainImg = document.getElementById('gallery-main-img');
  const thumbs = document.getElementById('gallery-thumbs');

  if (thumbs && mainImg) {
    thumbs.querySelectorAll('[data-gallery-src]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        mainImg.src = btn.dataset.gallerySrc;
        thumbs.querySelectorAll('.gallery-thumb').forEach(function (b) {
          b.classList.remove('is-active');
        });
        btn.classList.add('is-active');
      });
    });
  }

  // --- Detail images lightbox ---
  const dialog = document.querySelector('[data-detail-image-dialog]');
  const preview = dialog && dialog.querySelector('[data-detail-image-preview]');
  if (!dialog || !preview) {
    return;
  }

  document.querySelectorAll('[data-detail-image-open]').forEach((button) => {
    button.addEventListener('click', () => {
      preview.src = button.dataset.imageUrl;
      dialog.showModal();
    });
  });

  const closeButton = dialog.querySelector('[data-detail-image-close]');
  if (closeButton) {
    closeButton.addEventListener('click', () => dialog.close());
  }

  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) {
      dialog.close();
    }
  });

  dialog.addEventListener('close', () => {
    preview.src = '';
  });
})();

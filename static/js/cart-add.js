(function () {
  function getCookie(name) {
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : '';
  }

  function formatCount(count) {
    const number = Number(count);
    if (!Number.isFinite(number)) {
      return String(count);
    }
    if (Number.isInteger(number)) {
      return String(number);
    }
    const rounded = Math.round(number);
    if (Math.abs(number - rounded) < 1e-9) {
      return String(rounded);
    }
    return String(number).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');
  }

  function updateCartBadge(count) {
    const link = document.getElementById('cart-nav-link');
    if (!link) return;
    let badge = link.querySelector('.cart-badge');
    if (!count || count <= 0) {
      if (badge) badge.remove();
      return;
    }
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'cart-badge';
      link.appendChild(badge);
    }
    badge.textContent = formatCount(count);
  }

  function flyToCart(imageUrl, startEl) {
    const cartLink = document.getElementById('cart-nav-link');
    if (!cartLink || !imageUrl || !startEl) return;
    const startRect = startEl.getBoundingClientRect();
    const endRect = cartLink.getBoundingClientRect();
    const flyer = document.createElement('img');
    flyer.src = imageUrl;
    flyer.alt = '';
    flyer.className = 'cart-flyer';
    flyer.style.left = `${startRect.left + startRect.width / 2}px`;
    flyer.style.top = `${startRect.top + startRect.height / 2}px`;
    document.body.appendChild(flyer);
    requestAnimationFrame(() => {
      flyer.style.left = `${endRect.left + endRect.width / 2}px`;
      flyer.style.top = `${endRect.top + endRect.height / 2}px`;
      flyer.style.transform = 'translate(-50%, -50%) scale(0.12)';
      flyer.style.opacity = '0.25';
    });
    flyer.addEventListener('transitionend', () => {
      flyer.remove();
      cartLink.classList.add('cart-nav-link--pulse');
      window.setTimeout(() => cartLink.classList.remove('cart-nav-link--pulse'), 320);
    }, { once: true });
  }

  // Intercept submit buttons directly — avoids form submit event timing issues.
  document.addEventListener('click', function (event) {
    const button = event.target.closest('[data-quantity-change]');
    if (button) {
      const stepper = button.closest('.quantity-stepper');
      if (!stepper) return;
      const input = stepper.querySelector('input[name="qty"]');
      if (!input) return;
      const step = Number(input.step) || 1;
      const minimum = Number(input.min) || step;
      const current = Number(input.value) || minimum;
      const direction = Number(button.dataset.quantityChange);
      const precision = Math.max(
        (String(step).split('.')[1] || '').length,
        (String(minimum).split('.')[1] || '').length,
      );
      input.value = Math.max(minimum, current + direction * step).toFixed(precision);
      return;
    }

    const submitBtn = event.target.closest('[type="submit"]');
    if (!submitBtn) return;

    const form = submitBtn.closest('form');
    if (!form || !form.classList.contains('js-add-to-cart')) return;

    event.preventDefault();
    event.stopImmediatePropagation();

    submitBtn.disabled = true;

    fetch(form.action, {
      method: 'POST',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': getCookie('csrftoken'),
      },
      body: new FormData(form),
      credentials: 'same-origin',
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (response.status === 401 && data.redirect) {
          window.location.href = data.redirect;
          return;
        }
        if (!response.ok || !data.ok) {
          window.alert(data.error || '加入购物车失败，请稍后重试。');
          return;
        }
        updateCartBadge(data.cart_count);
        flyToCart(form.dataset.imageUrl || data.image_url, submitBtn);
      })
      .catch(() => {
        window.alert('加入购物车失败，请稍后重试。');
      })
      .finally(() => {
        submitBtn.disabled = false;
      });
  });

  // Cart quantity update: submit button click.
  document.addEventListener('click', function (event) {
    const button = event.target.closest('.js-cart-quantity [type="submit"]');
    if (!button) return;
    const form = button.closest('.js-cart-quantity');
    if (!form) return;
    const input = form.querySelector('input[name="qty"]');
    if (!input) return;

    event.preventDefault();
    button.disabled = true;

    fetch(form.action, {
      method: 'POST',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': getCookie('csrftoken'),
      },
      body: new FormData(form),
      credentials: 'same-origin',
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) {
          throw new Error(data.error || '购物车更新失败');
        }
        if (data.qty !== undefined && data.qty !== null) {
          input.value = formatCount(data.qty);
        }
        updateCartBadge(data.cart_count);
      })
      .catch(() => {
        window.alert('购物车更新失败，请稍后重试。');
      })
      .finally(() => {
        button.disabled = false;
      });
  });
})();

(function () {
  // Expand / collapse chips rows
  function initExpand(triggerId, chipsId, rowId) {
    const trigger = document.getElementById(triggerId);
    const chips = document.getElementById(chipsId);
    const row = document.getElementById(rowId);
    if (!trigger || !chips || !row) return;

    chips.style.transition = 'max-height 0.25s ease';
    chips.style.overflow = 'hidden';
    let isCollapsed = false;

    function collapse() {
      chips.style.maxHeight = chips.scrollHeight + 'px';
      requestAnimationFrame(function () {
        chips.style.maxHeight = '0px';
      });
      isCollapsed = true;
    }

    function expand() {
      chips.style.maxHeight = chips.scrollHeight + 'px';
      isCollapsed = false;
    }

    function check() {
      const chipsRect = chips.getBoundingClientRect();
      const rowRect = row.getBoundingClientRect();
      if (chipsRect.right > rowRect.right + 2) {
        trigger.style.display = 'inline-flex';
        if (!isCollapsed) collapse();
      } else {
        trigger.style.display = 'none';
        if (isCollapsed) expand();
      }
    }

    requestAnimationFrame(check);
    window.addEventListener('resize', check);

    trigger.addEventListener('click', function () {
      trigger.classList.toggle('is-expanded', !isCollapsed);
      const arrow = trigger.querySelector('.expand-arrow');
      const text = trigger.querySelector('.expand-text');
      if (arrow) arrow.style.transform = isCollapsed ? 'rotate(90deg)' : 'rotate(0deg)';
      if (text) text.textContent = isCollapsed ? '收起' : '展开更多';
      if (isCollapsed) { expand(); } else { collapse(); }
    });
  }

  initExpand('category-expand', 'category-chips', 'category-row');
  initExpand('brand-expand', 'brand-chips', 'brand-row');

  const region = document.querySelector('[data-product-region]');
  if (!region) return;

  let controller = null;

  async function loadPage(requestUrl) {
    if (controller) controller.abort();
    controller = new AbortController();
    region.classList.add('is-loading');

    try {
      const url = new URL(requestUrl, window.location.origin);
      const response = await fetch(url, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error('Network error');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const nextRegion = doc.querySelector('[data-product-region]');
      const nextCount = doc.querySelector('[data-product-count]');
      if (!nextRegion) throw new Error('Missing region');

      region.replaceChildren(...nextRegion.childNodes);
      const currentCount = document.querySelector('[data-product-count]');
      if (nextCount && currentCount) {
        currentCount.textContent = nextCount.textContent;
      }
      window.history.replaceState({}, '', `${url.pathname}${url.search}`);
    } catch (error) {
      if (error.name !== 'AbortError') {
        window.location.assign(requestUrl);
      }
    } finally {
      region.classList.remove('is-loading');
    }
  }

  region.addEventListener('click', (event) => {
    const link = event.target.closest('[data-product-pagination] a.page-button');
    if (link && !link.classList.contains('disabled')) {
      event.preventDefault();
      loadPage(link.href);
    }
  });

  region.addEventListener('submit', (event) => {
    const jumpForm = event.target.closest('.jump-form');
    if (!jumpForm) return;
    event.preventDefault();
    const input = jumpForm.querySelector('input[name="page"]');
    if (!input) return;
    const maxPage = Number(input.max) || 1;
    const raw = parseInt(input.value, 10);
    const target = Math.max(1, Math.min(maxPage, isNaN(raw) ? 1 : raw));
    const url = new URL(window.location.href);
    url.searchParams.set('page', String(target));
    loadPage(url.toString());
  });
})();

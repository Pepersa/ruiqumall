(function () {
  const form = document.querySelector('[data-variant-filter-form]');
  if (!form) return;

  // Panel header accordion toggle
  form.addEventListener('click', (e) => {
    const panel = e.target.closest('[data-filter-panel]');
    const toggleBtn = e.target.closest('[data-filter-toggle]');
    if (toggleBtn && panel) {
      panel.classList.toggle('is-closed');
    }
  });

  const results = document.querySelector('.variant-results');
  if (!results) return;

  let requestController = null;
  let requestSeq = 0;

  function buildQueryString() {
    const params = new URLSearchParams();
    // 保留当前 URL 里的 sku 参数，避免搜索后主 SKU 切换给用户造成「跳转到其他产品」错觉
    const currentSku = new URL(window.location.href).searchParams.get('sku');
    if (currentSku) {
      params.set('sku', currentSku);
    }
    // 筛选 form 的所有字段
    new FormData(form).forEach((value, key) => {
      if (value !== '' && value != null) params.append(key, value);
    });
    // 搜索框当前值（来自另一张 form）
    const searchInput = results.querySelector('.variant-search input[name="variant_q"]');
    if (searchInput && searchInput.value.trim()) {
      params.set('variant_q', searchInput.value.trim());
    } else {
      params.delete('variant_q');
    }
    return params.toString();
  }

  async function refreshVariants(requestUrl) {
    if (requestController) {
      requestController.abort();
    }
    requestController = new AbortController();
    const mySeq = ++requestSeq;

    const url = requestUrl
      ? new URL(requestUrl, window.location.origin)
      : new URL(form.action, window.location.origin);
    url.hash = '';
    if (!requestUrl) {
      url.search = buildQueryString();
    }
    results.classList.add('is-loading');
    form.setAttribute('aria-busy', 'true');

    try {
      const response = await fetch(url, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        signal: requestController.signal,
      });
      if (!response.ok) {
        throw new Error('Variant request failed');
      }
      // 仅处理最新请求的响应，避免竞态
      if (mySeq !== requestSeq) return;

      const documentCopy = new DOMParser().parseFromString(await response.text(), 'text/html');
      const nextRegion = documentCopy.querySelector('.variant-list-region');
      const nextCount = documentCopy.querySelector('.variant-result-count');
      const currentRegion = results.querySelector('.variant-list-region');
      const currentCount = document.querySelector('.variant-result-count');
      if (!nextRegion || !currentRegion) {
        throw new Error('Variant response is incomplete');
      }

      currentRegion.replaceChildren(...nextRegion.childNodes);
      if (nextCount && currentCount) {
        currentCount.textContent = nextCount.textContent;
      }
      // 仅在带 variant_q 或 sku 参数时刷新 URL，避免「输入即跳页面」的错觉
      const shouldUpdateUrl = url.searchParams.has('variant_q') || url.searchParams.has('sku');
      if (shouldUpdateUrl) {
        window.history.replaceState({}, '', `${url.pathname}${url.search}`);
      }
    } catch (error) {
      if (error.name !== 'AbortError' && mySeq === requestSeq) {
        window.location.assign(url);
      }
    } finally {
      if (mySeq === requestSeq) {
        results.classList.remove('is-loading');
        form.removeAttribute('aria-busy');
      }
    }
  }

  window.variantRefresh = refreshVariants;

  // Filter on checkbox change
  form.addEventListener('change', (event) => {
    if (event.target.matches('input[type="checkbox"]')) {
      refreshVariants();
    }
  });

  results.addEventListener('click', (event) => {
    const pageLink = event.target.closest('.variant-pagination a');
    if (pageLink) {
      event.preventDefault();
      window.variantRefresh(pageLink.href);
    }
  });

  results.addEventListener('submit', (event) => {
    const jumpForm = event.target.closest('[data-variant-jump]');
    if (!jumpForm) return;
    event.preventDefault();
    const input = jumpForm.elements.page;
    const maxPage = Number(input.max) || 1;
    const raw = parseInt(input.value, 10);
    const target = Math.max(1, Math.min(maxPage, isNaN(raw) ? 1 : raw));
    const url = new URL(window.location.href);
    url.searchParams.set('variant_page', String(target));
    window.variantRefresh(url.toString());
  });

  const clearLink = form.querySelector('[data-clear-variant-filters]');
  if (clearLink) {
    clearLink.addEventListener('click', (event) => {
      event.preventDefault();
      form.querySelectorAll('input[type="checkbox"]').forEach((input) => {
        input.checked = false;
      });
      const queryInput = form.querySelector('input[name="variant_q"]');
      if (queryInput) {
        queryInput.value = '';
      }
      refreshVariants();
    });
  }

  // Variant search box: only refresh on explicit submit (Enter/查询按钮).
  // 之前 input 事件触发防抖刷新，每打一字都会更新 URL，给用户「页面在跳」的错觉。
  const searchForm = results.querySelector('.variant-search');
  if (searchForm) {
    let debounceTimer = null;
    searchForm.addEventListener('submit', (event) => {
      event.preventDefault();
      clearTimeout(debounceTimer);
      refreshVariants();
    });
  }
})();

(function () {
  'use strict';
  // 顶部搜索框：实时搜索建议下拉（autocomplete）。
  // 输入框与下拉面板的关系：下拉挂在 input 的父元素 .header-search 内。
  const forms = document.querySelectorAll('form.top-search');
  if (!forms.length) return;

  forms.forEach(function (form) {
    const input = form.querySelector('input[name="q"]');
    if (!input) return;
    // 防止重复挂载
    if (form.dataset.suggestInit === '1') return;
    form.dataset.suggestInit = '1';

    const suggestUrl = form.dataset.suggestUrl || '/catalog/search/suggest/';
    const wrapper = form.parentElement; // .header-search

    // 创建下拉容器
    const panel = document.createElement('div');
    panel.className = 'search-suggest-panel';
    panel.setAttribute('role', 'listbox');
    panel.hidden = true;
    wrapper.appendChild(panel);

    let lastQuery = '';
    let lastToken = 0;
    let activeIndex = -1;
    let currentItems = []; // [{label, sub, url, type}]

    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, function (c) {
        return ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c];
      });
    }

    function highlight(text, term) {
      if (!term) return escapeHtml(text);
      const lowerText = String(text).toLowerCase();
      const lowerTerm = term.toLowerCase();
      const idx = lowerText.indexOf(lowerTerm);
      if (idx < 0) return escapeHtml(text);
      return (
        escapeHtml(text.slice(0, idx)) +
        '<mark>' + escapeHtml(text.slice(idx, idx + term.length)) + '</mark>' +
        escapeHtml(text.slice(idx + term.length))
      );
    }

    function close() {
      panel.hidden = true;
      panel.innerHTML = '';
      activeIndex = -1;
      currentItems = [];
    }

    function render(payload, term) {
      currentItems = [];
      const skus = (payload && payload.skus) || [];
      const products = (payload && payload.products) || [];
      let html = '';
      if (skus.length) {
        html += '<div class="search-suggest-section">型号</div>';
        skus.slice(0, 6).forEach(function (s) {
          currentItems.push({ type: 'sku', url: s.url });
          html +=
            '<a class="search-suggest-item" data-idx="' + (currentItems.length - 1) +
            '" href="' + s.url + '" role="option">' +
            '<span class="search-suggest-name">' + highlight(s.internal_sku_code, term) + '</span>' +
            '<span class="search-suggest-sub">' + escapeHtml(s.product_name) + '</span>' +
            '</a>';
        });
      }
      if (products.length) {
        html += '<div class="search-suggest-section">产品</div>';
        products.slice(0, 6).forEach(function (p) {
          currentItems.push({ type: 'product', url: p.url });
          const subBits = [];
          if (p.brand) subBits.push(p.brand);
          if (p.manufacturer_model) subBits.push(p.manufacturer_model);
          html +=
            '<a class="search-suggest-item" data-idx="' + (currentItems.length - 1) +
            '" href="' + p.url + '" role="option">' +
            '<span class="search-suggest-name">' + highlight(p.name, term) + (p.alias ? ' <span class="alias">' + escapeHtml(p.alias) + '</span>' : '') + '</span>' +
            (subBits.length ? '<span class="search-suggest-sub">' + escapeHtml(subBits.join(' · ')) + '</span>' : '') +
            '</a>';
        });
      }
      if (!html) {
        panel.innerHTML = '<div class="search-suggest-empty">无匹配建议</div>';
      } else {
        panel.innerHTML = html;
        // 末尾"查看全部结果"
        panel.insertAdjacentHTML(
          'beforeend',
          '<a class="search-suggest-more" href="' +
            '?q=' + encodeURIComponent(term) +
            '" data-suggest-more>查看全部 " ' + escapeHtml(term) + ' " 的搜索结果 ›</a>'
        );
      }
      activeIndex = -1;
      updateActive();
      panel.hidden = false;
    }

    function updateActive() {
      const items = panel.querySelectorAll('[data-idx]');
      items.forEach(function (el) {
        el.classList.remove('is-active');
      });
      if (activeIndex >= 0 && items[activeIndex]) {
        items[activeIndex].classList.add('is-active');
      }
    }

    let timer = null;
    function fetchSuggest(term) {
      if (timer) clearTimeout(timer);
      if (!term || term.length < 1) {
        close();
        return;
      }
      timer = setTimeout(function () {
        const myToken = ++lastToken;
        const url = suggestUrl + '?q=' + encodeURIComponent(term);
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (data) {
            if (myToken !== lastToken) return; // 已被新请求取代
            if (!data) { close(); return; }
            lastQuery = term;
            render(data, term);
          })
          .catch(function () { /* ignore */ });
      }, 150);
    }

    input.addEventListener('input', function () {
      const term = input.value.trim();
      if (term === lastQuery) return;
      fetchSuggest(term);
    });
    input.addEventListener('focus', function () {
      const term = input.value.trim();
      if (term) fetchSuggest(term);
    });
    input.addEventListener('blur', function () {
      // 延迟关闭，允许下拉中的点击生效
      setTimeout(close, 150);
    });
    input.addEventListener('keydown', function (event) {
      if (panel.hidden) {
        if (event.key === 'ArrowDown') {
          const term = input.value.trim();
          if (term) fetchSuggest(term);
        }
        return;
      }
      const items = panel.querySelectorAll('[data-idx]');
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        activeIndex = (activeIndex + 1) % items.length;
        updateActive();
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        activeIndex = (activeIndex - 1 + items.length) % items.length;
        updateActive();
      } else if (event.key === 'Enter') {
        if (activeIndex >= 0 && items[activeIndex]) {
          event.preventDefault();
          items[activeIndex].click();
        }
      } else if (event.key === 'Escape') {
        close();
      }
    });

    document.addEventListener('click', function (event) {
      if (!wrapper.contains(event.target)) close();
    });
  });
})();
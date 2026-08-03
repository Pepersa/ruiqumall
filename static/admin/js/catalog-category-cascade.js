'use strict';
(function () {
  function findField(name) {
    return document.querySelector('[id$="-name"]'.replace('-name', '-name').replace('id$="-name"]', `id$="-${name}"]`)) ||
           document.querySelector(`[id*="-${name}"]`) ||
           document.querySelector(`[name*="${name}"]`);
  }

  function findSelect(name) {
    var el = document.getElementById('id_' + name);
    if (!el) {
      var candidates = document.querySelectorAll('select[name="' + name + '"]');
      if (candidates.length) el = candidates[0];
    }
    return el;
  }

  window.addEventListener('DOMContentLoaded', function () {
    var f1 = findSelect('category_l1');
    var f2 = findSelect('category_l2');
    var f3 = findSelect('category_l3');
    if (!f1 || !f2 || !f3) return;

    var originalOnchange1 = f1.onchange;
    var originalOnchange2 = f2.onchange;

    function setOptions(select, options, placeholder) {
      select.innerHTML = '';
      var ph = document.createElement('option');
      ph.value = '';
      ph.textContent = placeholder;
      select.appendChild(ph);
      options.forEach(function (opt) {
        var o = document.createElement('option');
        o.value = opt.value;
        o.textContent = opt.label;
        select.appendChild(o);
      });
    }

    f2.disabled = false;
    f3.disabled = false;

    f1.addEventListener('change', function () {
      f2.value = '';
      f3.value = '';
      f2.dispatchEvent(new Event('change', { bubbles: true }));
      f3.dispatchEvent(new Event('change', { bubbles: true }));
      if (originalOnchange1) originalOnchange1.call(f1);
    });

    f2.addEventListener('change', function () {
      f3.value = '';
      f3.dispatchEvent(new Event('change', { bubbles: true }));
      if (originalOnchange2) originalOnchange2.call(f2);
    });

    // Label the three fields as a group
    [f1, f2, f3].forEach(function (el) {
      el.style.display = '';
    });
  });
})();

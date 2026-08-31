'use strict';
(function () {
  // HomeBrand 品牌名称下拉框：启动时向 API 获取所有已有产品品牌，追加到下拉列表
  var selectId = 'id_name';
  var sel = document.getElementById(selectId);
  if (!sel) return;

  // 记下当前已选值
  var currentValue = sel.value;

  // 先填满占位选项（表单初始值）
  fetch('/admin/catalog/homebrand/api-brands/')
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (brands) {
      if (!brands || !Array.isArray(brands)) return;
      // 清空仅保留第一项占位
      while (sel.options.length > 1) sel.remove(1);
      brands.forEach(function (brand) {
        var opt = document.createElement('option');
        opt.value = brand;
        opt.textContent = brand;
        if (brand === currentValue) opt.selected = true;
        sel.appendChild(opt);
      });
    })
    .catch(function () { /* 网络错误不影响表单提交 */ });
})();

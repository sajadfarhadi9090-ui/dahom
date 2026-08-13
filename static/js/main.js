/* کلاس دهم — اسکریپت‌های عمومی */
(function () {
  'use strict';

  /* ---------- تب‌بندی صفحات درس ---------- */
  document.querySelectorAll('.tabs').forEach(function (tabs) {
    var panels = {};
    var firstActive = null;
    tabs.querySelectorAll('.tab-btn').forEach(function (btn) {
      var key = btn.getAttribute('data-tab');
      panels[key] = document.querySelector('.tab-panel[data-panel="' + key + '"]');
      if (!firstActive && panels[key] && panels[key].querySelector('.item-row, .empty')) {
        firstActive = key;
      }
      btn.addEventListener('click', function () {
        tabs.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
        Object.keys(panels).forEach(function (k) {
          if (panels[k]) panels[k].classList.remove('active');
        });
        btn.classList.add('active');
        if (panels[key]) panels[key].classList.add('active');
      });
    });
    /* اگر تب پیش‌فرض (اول) محتوایی نداشت، تب دارای محتوا فعال شود */
    if (firstActive) {
      var activeBtn = tabs.querySelector('.tab-btn[data-tab="' + firstActive + '"]');
      if (activeBtn && !activeBtn.classList.contains('active')) activeBtn.click();
    }
  });

  /* ---------- تأیید حذف ---------- */
  document.querySelectorAll('[data-confirm]').forEach(function (el) {
    el.addEventListener('submit', function (e) {
      if (!window.confirm(el.getAttribute('data-confirm'))) {
        e.preventDefault();
      }
    });
  });

  /* ---------- مخفی‌شدن خودکار پیام‌ها ---------- */
  var flashes = document.querySelectorAll('.flash');
  if (flashes.length) {
    setTimeout(function () {
      flashes.forEach(function (f) {
        f.style.transition = 'opacity .4s';
        f.style.opacity = '0';
        setTimeout(function () { f.remove(); }, 450);
      });
    }, 4200);
  }

  /* ---------- فرم بارگذاری: فایل یا لینک ---------- */
  var sourceRadios = document.querySelectorAll('input[name="source_type"]');
  if (sourceRadios.length) {
    var fileGroup = document.getElementById('file-group');
    var urlGroup = document.getElementById('url-group');
    function toggleSource() {
      var val = document.querySelector('input[name="source_type"]:checked');
      if (!val) return;
      if (val.value === 'file') {
        fileGroup.style.display = 'block';
        urlGroup.style.display = 'none';
      } else {
        fileGroup.style.display = 'none';
        urlGroup.style.display = 'block';
      }
    }
    sourceRadios.forEach(function (r) { r.addEventListener('change', toggleSource); });
    toggleSource();
  }

  /* ---------- انتخاب سریع «مشترک همه رشته‌ها» در فرم درس ---------- */
  var commonToggle = document.getElementById('all-fields-toggle');
  var fieldChecks = document.querySelectorAll('input[name="fields"]');
  if (commonToggle && fieldChecks.length) {
    commonToggle.addEventListener('change', function () {
      fieldChecks.forEach(function (c) { c.checked = commonToggle.checked; });
    });
  }
})();

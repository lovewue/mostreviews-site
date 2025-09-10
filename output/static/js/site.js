// /static/js/site.js
(function () {
  const btn = document.querySelector('[data-mobile-menu-toggle="menu"]');
  const drawer = document.getElementById('menu');
  const backdrop = document.querySelector('.nav-backdrop');
  const closeBtn = drawer ? drawer.querySelector('.drawer-close') : null;

  if (!btn || !drawer) return;

  function openNav() {
    btn.setAttribute('aria-expanded', 'true');
    document.body.classList.add('nav-open', 'no-scroll');
  }

  function closeNav() {
    btn.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('nav-open', 'no-scroll');
  }

  function toggleNav(e) {
    e?.preventDefault();
    (btn.getAttribute('aria-expanded') === 'true') ? closeNav() : openNav();
  }

  btn.addEventListener('click', toggleNav);
  backdrop?.addEventListener('click', closeNav);
  closeBtn?.addEventListener('click', closeNav);
})();

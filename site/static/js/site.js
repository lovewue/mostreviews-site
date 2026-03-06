// /static/js/site.js
(function () {
  const btn = document.querySelector('[data-mobile-menu-toggle="menu"]');
  const drawer = document.getElementById('menu');
  const backdrop = document.querySelector('.nav-backdrop');
  const closeBtn = drawer ? drawer.querySelector('.drawer-close') : null; // NEW

  if (!btn || !drawer) return;

  function openNav() {
    btn.setAttribute('aria-expanded', 'true');
    drawer.hidden = false;
    document.body.classList.add('nav-open', 'no-scroll');
    const firstFocusable = drawer.querySelector('a, button, [tabindex]:not([tabindex="-1"])');
    firstFocusable && firstFocusable.focus({ preventScroll: true });
  }

  function closeNav() {
    btn.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('nav-open', 'no-scroll');
    setTimeout(() => { drawer.hidden = true; }, 250);
    btn.focus({ preventScroll: true });
  }

  function toggleNav(e) {
    e?.preventDefault();
    (btn.getAttribute('aria-expanded') === 'true') ? closeNav() : openNav();
  }

  // Event bindings
  btn.addEventListener('click', toggleNav);
  backdrop?.addEventListener('click', closeNav);
  closeBtn?.addEventListener('click', closeNav);
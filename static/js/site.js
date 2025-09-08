// /static/js/site.js
(function () {
  // Button must have: data-mobile-menu-toggle="menu"
  // Drawer must be:   <nav id="menu" class="nav-drawer" hidden>
  // Backdrop:         <div class="nav-backdrop" aria-hidden="true"></div>

  const btn = document.querySelector('[data-mobile-menu-toggle="menu"]');
  const drawer = document.getElementById('menu');
  const backdrop = document.querySelector('.nav-backdrop');

  if (!btn || !drawer) return; // nothing to do if markup not present

  function openNav() {
    btn.setAttribute('aria-expanded', 'true');
    drawer.hidden = false;
    document.body.classList.add('nav-open', 'no-scroll');

    // Optional: focus first focusable item inside the drawer
    const firstFocusable = drawer.querySelector('a, button, input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (firstFocusable) {
      // Prevent the page from auto-scrolling when focusing
      firstFocusable.focus({ preventScroll: true });
    }
  }

  function closeNav() {
    btn.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('nav-open', 'no-scroll');

    // Wait for CSS transition to finish before hiding from ATs
    setTimeout(() => { drawer.hidden = true; }, 250);

    // Return focus to the toggle for accessibility
    btn.focus({ preventScroll: true });
  }

  function toggleNav(e) {
    e?.preventDefault();
    (btn.getAttribute('aria-expanded') === 'true') ? closeNav() : openNav();
  }

  // Events
  btn.addEventListener('click', toggleNav);
  backdrop?.addEventListener('click', closeNav);

  // Close on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && btn.getAttribute('aria-expanded') === 'true') {
      closeNav();
    }
  });

  // Close after clicking any link inside the drawer
  drawer.addEventListener('click', (e) => {
    if (e.target.closest('a')) closeNav();
  });

  // Safety: if user resizes to desktop while open, ensure proper state
  const DESKTOP_BP = 901; // match your CSS @media (min-width: 901px)
  window.addEventListener('resize', () => {
    if (window.innerWidth >= DESKTOP_BP) {
      // Instantly sync to desktop layout
      btn.setAttribute('aria-expanded', 'false');
      drawer.hidden = false; // nav is visible inline on desktop
      document.body.classList.remove('nav-open', 'no-scroll');
    } else {
      // On mobile, hide the drawer by default
      if (btn.getAttribute('aria-expanded') !== 'true') {
        drawer.hidden = true;
      }
    }
  });
})();

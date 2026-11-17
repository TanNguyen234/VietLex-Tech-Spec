(() => {
  document.querySelectorAll('.admin-bar[data-bar-height]').forEach((bar) => {
    const pct = Number(bar.dataset.barHeight);
    if (Number.isFinite(pct) && pct >= 0 && pct <= 100) {
      bar.style.height = `${pct}%`;
    }
  });
  const navigation = document.querySelector('.admin-mobile-nav');
  if (!navigation) return;
  const mobile = window.matchMedia('(max-width: 760px)');
  const updateNavigation = () => { navigation.open = !mobile.matches; };
  updateNavigation();
  mobile.addEventListener('change', updateNavigation);
})();

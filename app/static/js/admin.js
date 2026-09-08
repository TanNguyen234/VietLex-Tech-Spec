(() => {
  const navigation = document.querySelector('.admin-mobile-nav');
  if (!navigation) return;
  const mobile = window.matchMedia('(max-width: 760px)');
  const updateNavigation = () => { navigation.open = !mobile.matches; };
  updateNavigation();
  mobile.addEventListener('change', updateNavigation);
})();

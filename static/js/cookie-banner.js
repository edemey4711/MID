(function() {
  const banner = document.getElementById('cookie-banner');
  const acceptBtn = document.getElementById('cookie-accept');
  
  if (!banner || !acceptBtn) return;
  
  // Prüfen ob User bereits zugestimmt hat
  if (!localStorage.getItem('cookiesAccepted')) {
    banner.classList.add('show');
  }
  
  // Accept Button Handler
  acceptBtn.addEventListener('click', function() {
    localStorage.setItem('cookiesAccepted', 'true');
    banner.classList.remove('show');
  });
})();

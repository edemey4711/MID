(function(){
  const el = document.getElementById('detail-data');
  if (!el) return;
  const lat = parseFloat(el.getAttribute('data-lat'));
  const lon = parseFloat(el.getAttribute('data-lon'));
  const map = L.map('detailMap').setView([lat, lon], 15);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);

  const menInDreckIcon = L.icon({
    iconUrl: "/static/icons/men-in-dreck-helmet.svg",
    iconSize: [48, 48],
    iconAnchor: [24, 48],
    popupAnchor: [0, -48]
  });

  L.marker([lat, lon], { icon: menInDreckIcon }).addTo(map);
})();

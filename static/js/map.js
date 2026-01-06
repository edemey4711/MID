(function(){
  const dataEl = document.getElementById('images-data');
  const images = dataEl ? JSON.parse(dataEl.getAttribute('data-images') || '[]') : [];

  const menInDreckHelmetBadge = L.icon({
    iconUrl: "/static/icons/men-in-dreck-helmet.svg",
    iconSize: [48, 48],
    iconAnchor: [24, 48],
    popupAnchor: [0, -48],
  });

  const categoryIcons = {
    Burg: L.icon({ iconUrl: "/static/icons/burg.svg", iconSize: [48, 48], iconAnchor: [24, 48], popupAnchor: [0, -48] }),
    Fels: L.icon({ iconUrl: "/static/icons/fels.svg", iconSize: [48, 48], iconAnchor: [24, 48], popupAnchor: [0, -48] }),
    Kirche: L.icon({ iconUrl: "/static/icons/kirche.svg", iconSize: [48, 48], iconAnchor: [24, 48], popupAnchor: [0, -48] }),
    Aussicht: L.icon({ iconUrl: "/static/icons/aussicht.svg", iconSize: [48, 48], iconAnchor: [24, 48], popupAnchor: [0, -48] }),
  };

  const defaultIcon = L.icon({ iconUrl: "/static/icons/default.svg", iconSize: [48, 48], iconAnchor: [24, 48], popupAnchor: [0, -48] });

  const map = L.map("map").setView([51.1657, 10.4515], 6);
  const markerCluster = L.markerClusterGroup();

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19 }).addTo(map);

  const markers = [];
  const markersById = {};

  images.forEach((img) => {
    const name = img[1] || "";
    const description = img[2] || "";
    const category = img[3] || "";
    const filepath = img[4] || "";
    let lat = img[5];
    let lon = img[6];

    if (!lat || isNaN(lat)) lat = 51.1657;
    if (!lon || isNaN(lon)) lon = 10.4515;

    const icon = categoryIcons[category] || defaultIcon;

    const marker = L.marker([lat, lon], { icon });
    marker.category = category;
    markerCluster.addLayer(marker);
    markers.push(marker);
    markersById[String(img[0])] = marker;

    marker.bindPopup(`
      <div style="max-width:200px">
          <h5 class="fw-bold mb-1">${name}</h5>
          <span class="badge bg-warning text-dark mb-2">${category}</span>
          <p>${description}</p>
          <img src="/uploads/${filepath}" class="img-fluid rounded mb-2">
          <a href="/detail/${img[0]}" class="btn btn-warning btn-sm w-100">Details ansehen</a>
      </div>
    `);
  });

  map.addLayer(markerCluster);

  const selectEl = document.getElementById("category-select");
  if (selectEl) {
    selectEl.addEventListener("change", function () {
      const selected = this.value;
      markers.forEach((marker) => {
        if (selected === "Alle" || marker.category === selected) {
          markerCluster.addLayer(marker);
        } else {
          markerCluster.removeLayer(marker);
        }
      });
    });
  }

  const params = new URLSearchParams(window.location.search);
  const focus = params.get('focus');
  if (focus && markersById[focus]) {
    const m = markersById[focus];
    markerCluster.zoomToShowLayer(m, function () {
      map.setView(m.getLatLng(), 15);
      m.openPopup();
    });
  }
})();

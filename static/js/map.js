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

  // --- Verschiedene Kartenlagen (Basemaps) ---
  const osmLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors',
    errorTileUrl: ''
  });
  
  const topoLayer = L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
    maxZoom: 17,
    attribution: '© OpenTopoMap contributors',
    errorTileUrl: ''
  });
  
  const satelliteLayer = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 19,
    attribution: '© Esri',
    errorTileUrl: ''
  });

  // Standardlayer beim Start
  osmLayer.addTo(map);

  // Layer-Control hinzufügen
  const baseLayers = {
    "🗺️ OpenStreetMap": osmLayer,
    "🏔️ Topographie": topoLayer,
    "🛰️ Satellit": satelliteLayer
  };

  const layerControl = L.control.layers(baseLayers, null, {
    position: 'topright',
    collapsed: true
  }).addTo(map);

  // Debug-Logging für Layer-Wechsel
  map.on('baselayerchange', function(e) {
    console.log('Layer gewechselt zu: ' + e.name);
  });

  const markers = [];
  const markersById = {};
  let allImages = [];

  images.forEach((img) => {
    const name = img[1] || "";
    const description = img[2] || "";
    const category = img[3] || "";
    const filepath = img[4] || "";
    const thumbnail_path = img[5] || "";
    let lat = img[6];
    let lon = img[7];

    if (!lat || isNaN(lat)) lat = 51.1657;
    if (!lon || isNaN(lon)) lon = 10.4515;

    const icon = categoryIcons[category] || defaultIcon;

    const marker = L.marker([lat, lon], { icon });
    marker.category = category;
    marker.name = name;
    marker.imageId = img[0];
    markerCluster.addLayer(marker);
    markers.push(marker);
    markersById[String(img[0])] = marker;

    // Speichere Bildinfo für Sidebar
    allImages.push({
      id: img[0],
      name: name,
      category: category,
      thumbnail: thumbnail_path || filepath
    });

    // Nutze Thumbnail wenn vorhanden, sonst Vollbild
    const image_src = thumbnail_path ? `/thumbnails/${thumbnail_path}` : `/uploads/${filepath}`;

    marker.bindPopup(`
      <div style="max-width:200px">
          <h5 class="fw-bold mb-1">${name}</h5>
          <span class="badge bg-warning text-dark mb-2">${category}</span>
          <p>${description}</p>
          <img src="${image_src}" class="img-fluid rounded mb-2" loading="lazy" alt="${name}">
          <a href="/detail/${img[0]}" class="btn btn-warning btn-sm w-100">Details ansehen</a>
      </div>
    `);
  });

  map.addLayer(markerCluster);

  // --- SIDEBAR FUNKTIONALITÄT ---
  const sidebar = document.getElementById("sidebar");
  const sidebarToggle = document.getElementById("sidebar-toggle");
  const sidebarClose = document.getElementById("sidebar-close");
  const imageList = document.getElementById("image-list");
  const sidebarSearch = document.getElementById("sidebar-search");

  // Sidebar initial immer geschlossen (Desktop und Mobile)
  if (sidebar) {
    sidebar.classList.add("closed");
    document.body.classList.add("sidebar-closed");
  }

  // Helper: Toggle Button aktualisieren
  const updateToggleButtonVisibility = () => {
    if (!sidebarToggle) return;
    if (sidebar?.classList.contains("closed")) {
      sidebarToggle.style.display = "flex";
    } else {
      sidebarToggle.style.display = "none";
    }
  };

  // Sidebar öffnen
  if (sidebarToggle) {
    sidebarToggle.addEventListener("click", () => {
      sidebar?.classList.remove("closed");
      sidebar?.classList.add("open");
      document.body.classList.remove("sidebar-closed");
      document.body.classList.add("sidebar-open");
      updateToggleButtonVisibility();
      // Leaflet Map nach CSS-Transition neu berechnen
      setTimeout(() => map.invalidateSize(), 300);
    });
  }

  // Sidebar schließen (auf Mobile und Desktop)
  if (sidebarClose) {
    sidebarClose.addEventListener("click", () => {
      sidebar?.classList.add("closed");
      sidebar?.classList.remove("open");
      document.body.classList.add("sidebar-closed");
      document.body.classList.remove("sidebar-open");
      updateToggleButtonVisibility();
      // Leaflet Map nach CSS-Transition neu berechnen
      setTimeout(() => map.invalidateSize(), 300);
    });
  }

  // Initial visibility
  updateToggleButtonVisibility();

  // Bilderliste populieren
  function renderImageList(imagesToShow = allImages) {
    imageList.innerHTML = imagesToShow.map(img => `
      <div class="image-item" data-image-id="${img.id}">
        <img src="/thumbnails/${img.thumbnail}" class="image-item-thumb" alt="${img.name}" loading="lazy">
        <div class="image-item-info">
          <div class="image-item-name">${img.name}</div>
          <span class="badge bg-warning text-dark">${img.category}</span>
        </div>
      </div>
    `).join("");

    // Click-Handler für Bilderliste
    document.querySelectorAll(".image-item").forEach(item => {
      item.addEventListener("click", () => {
        const imageId = item.getAttribute("data-image-id");
        const marker = markersById[imageId];
        if (marker) {
          markerCluster.zoomToShowLayer(marker, () => {
            map.setView(marker.getLatLng(), 15);
            marker.openPopup();
          });
          sidebar?.classList.remove("open");
        }
      });
    });
  }

  // Suche in Bilderliste
  if (sidebarSearch) {
    sidebarSearch.addEventListener("input", (e) => {
      const query = e.target.value.toLowerCase();
      const filtered = query
        ? allImages.filter(img => img.name.toLowerCase().includes(query))
        : allImages;
      renderImageList(filtered);
    });
  }

  // Initial render
  renderImageList();
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

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

function isValidLocation(location) {
  return (
    Number.isFinite(location?.latitude) &&
    location.latitude >= -90 &&
    location.latitude <= 90 &&
    Number.isFinite(location?.longitude) &&
    location.longitude >= -180 &&
    location.longitude <= 180
  );
}

function markerIcon(kind) {
  return L.divIcon({
    className: "interactive-map__marker-icon",
    html: `<span class="interactive-map__marker interactive-map__marker--${kind}"></span>`,
    iconSize: [20, 20],
    iconAnchor: [10, 10],
  });
}

function formatCaptureDate(value) {
  if (!value) return "Not available";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Not available" : date.toLocaleString();
}

export default function InteractiveMap({
  taskLocation,
  workerLocation,
  locationLabel = "Accepted worker arrival location",
  locationKind = "worker",
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markersRef = useRef(null);
  const taskLocationIsValid = isValidLocation(taskLocation);

  useEffect(() => {
    if (!containerRef.current || !taskLocationIsValid) return;

    const map = L.map(containerRef.current, {
      center: [taskLocation.latitude, taskLocation.longitude],
      zoom: 15,
      scrollWheelZoom: false,
    });
    const markers = L.featureGroup().addTo(map);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);

    mapRef.current = map;
    markersRef.current = markers;

    let active = true;
    const invalidateSize = () => {
      requestAnimationFrame(() => {
        if (active && mapRef.current === map) {
          map.invalidateSize({ pan: false });
        }
      });
    };
    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(invalidateSize);
    resizeObserver?.observe(containerRef.current);
    window.addEventListener("resize", invalidateSize);
    invalidateSize();

    return () => {
      active = false;
      resizeObserver?.disconnect();
      window.removeEventListener("resize", invalidateSize);
      map.remove();
      mapRef.current = null;
      markersRef.current = null;
    };
  }, [taskLocationIsValid]);

  useEffect(() => {
    const map = mapRef.current;
    const markers = markersRef.current;
    if (!map || !markers || !isValidLocation(taskLocation)) return;

    markers.clearLayers();
    const bounds = [];
    const assigned = L.marker(
      [taskLocation.latitude, taskLocation.longitude],
      {
        icon: markerIcon("assigned"),
        title: `Assigned task location: ${taskLocation.label}`,
        alt: "Assigned task location",
      },
    )
      .bindTooltip(`Assigned task: ${taskLocation.label}`)
      .addTo(markers);
    bounds.push(assigned.getLatLng());

    if (isValidLocation(workerLocation)) {
      const accuracy =
        Number.isFinite(workerLocation.accuracyMeters) &&
        workerLocation.accuracyMeters > 0
          ? `, accuracy ±${workerLocation.accuracyMeters.toFixed(1)} m`
          : "";
      const captured = L.marker(
        [workerLocation.latitude, workerLocation.longitude],
        {
          icon: markerIcon(locationKind),
          title: workerLocation.isAccepted
            ? locationLabel
            : "Current worker GPS fix, not yet saved",
          alt: workerLocation.isAccepted
            ? locationLabel
            : "Current worker GPS fix, not yet saved",
        },
      )
        .bindTooltip(
        `${
          workerLocation.isAccepted
            ? locationLabel
            : "Current worker GPS fix (not saved)"
        }${accuracy}`,
      )
        .addTo(markers);
      bounds.push(captured.getLatLng());
    }

    if (bounds.length > 1) {
      map.fitBounds(L.latLngBounds(bounds), { padding: [36, 36], maxZoom: 16 });
    } else {
      map.setView(bounds[0], 15);
    }
  }, [taskLocation, workerLocation]);

  if (!isValidLocation(taskLocation)) {
    return (
      <p className="interactive-map__unavailable" role="status">
        A map cannot be shown because the task coordinates are invalid.
      </p>
    );
  }

  return (
    <div className="interactive-map">
      <div
        aria-label={`Interactive map showing assigned task and ${locationLabel.toLowerCase()}`}
        className="interactive-map__canvas"
        ref={containerRef}
        role="application"
      />
      <ul className="interactive-map__legend" aria-label="Map markers">
        <li>
          <span className="interactive-map__legend-marker interactive-map__legend-marker--assigned" />
          Assigned task location: {taskLocation.label}
        </li>
        {isValidLocation(workerLocation) && (
          <li>
            <span
              className={`interactive-map__legend-marker interactive-map__legend-marker--${locationKind}`}
            />
            {workerLocation.isAccepted
              ? locationLabel
              : "Current worker GPS fix (not saved)"}
          </li>
        )}
      </ul>
      {isValidLocation(workerLocation) ? (
        <dl className="interactive-map__worker-details">
          <div>
            <dt>Latitude</dt>
            <dd>{workerLocation.latitude}</dd>
          </div>
          <div>
            <dt>Longitude</dt>
            <dd>{workerLocation.longitude}</dd>
          </div>
          <div>
            <dt>Reported accuracy</dt>
            <dd>
              {Number.isFinite(workerLocation.accuracyMeters) &&
              workerLocation.accuracyMeters > 0
                ? `±${workerLocation.accuracyMeters.toFixed(1)} m`
                : "Not available"}
            </dd>
          </div>
          <div>
            <dt>Captured</dt>
            <dd>{formatCaptureDate(workerLocation.capturedAt)}</dd>
          </div>
          <div>
            <dt>Location status</dt>
            <dd>
              {workerLocation.isAccepted
                ? "Accepted for task progression"
                : "Current fix; not saved"}
            </dd>
          </div>
        </dl>
      ) : (
        <p className="interactive-map__empty" role="status">
          No accepted worker arrival location is available yet. Capture and
          save an acceptable GPS fix to show the worker marker.
        </p>
      )}
      <p className="interactive-map__attribution">
        Map data &copy; OpenStreetMap contributors. Map tiles require an
        internet connection and are subject to the{" "}
        <a href="https://operations.osmfoundation.org/policies/tiles/">
          tile usage policy
        </a>
        .
      </p>
    </div>
  );
}

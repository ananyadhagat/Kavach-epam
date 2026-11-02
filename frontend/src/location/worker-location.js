function hasValidCoordinates(location) {
  return (
    Number.isFinite(location?.latitude) &&
    location.latitude >= -90 &&
    location.latitude <= 90 &&
    Number.isFinite(location?.longitude) &&
    location.longitude >= -180 &&
    location.longitude <= 180
  );
}

function isAcceptedArrivalEvent(event) {
  return (
    event?.event_type === "ARRIVAL" &&
    event.capture_status === "CAPTURED" &&
    event.accepted_for_progress === true &&
    hasValidCoordinates(event) &&
    Number.isFinite(event.accuracy_meters) &&
    event.accuracy_meters > 0
  );
}

function toWorkerLocation(event, isAccepted) {
  return {
    latitude: event.latitude,
    longitude: event.longitude,
    eventType: "ARRIVAL",
    accuracyMeters: event.accuracy_meters,
    capturedAt: event.captured_at_device,
    receivedAt: event.received_at_server,
    isAccepted,
  };
}

export function getAcceptedArrivalLocation(task) {
  if (
    task?.arrival_location_accepted !== true ||
    typeof task.arrival_location_event_id !== "string"
  ) {
    return null;
  }

  const event =
    task.accepted_arrival_location ??
    (task.latest_arrival_location?.accepted_for_progress === true
      ? task.latest_arrival_location
      : null);

  return isAcceptedArrivalEvent(event) &&
    event.location_event_id === task.arrival_location_event_id
    ? toWorkerLocation(event, true)
    : null;
}

export function getWorkerLocationForMap(task, currentLocation) {
  const acceptedLocation = getAcceptedArrivalLocation(task);
  if (!hasValidCoordinates(currentLocation)) return acceptedLocation;
  if (currentLocation.isAccepted !== true || !acceptedLocation) {
    return currentLocation;
  }

  const currentReceivedAt = Date.parse(currentLocation.receivedAt ?? "");
  const acceptedReceivedAt = Date.parse(acceptedLocation.receivedAt ?? "");
  return Number.isFinite(currentReceivedAt) &&
    Number.isFinite(acceptedReceivedAt) &&
    acceptedReceivedAt > currentReceivedAt
    ? acceptedLocation
    : currentLocation;
}

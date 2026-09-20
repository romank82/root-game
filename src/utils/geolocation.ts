export function calculateDistanceInMeters(
  firstLatitude: number,
  firstLongitude: number,
  secondLatitude: number,
  secondLongitude: number,
): number {
  const earthRadiusMeters = 6371000
  const latitudeDifference = ((secondLatitude - firstLatitude) * Math.PI) / 180
  const longitudeDifference = ((secondLongitude - firstLongitude) * Math.PI) / 180

  const firstLatitudeRadians = (firstLatitude * Math.PI) / 180
  const secondLatitudeRadians = (secondLatitude * Math.PI) / 180

  const value =
    Math.sin(latitudeDifference / 2) * Math.sin(latitudeDifference / 2) +
    Math.cos(firstLatitudeRadians) *
      Math.cos(secondLatitudeRadians) *
      Math.sin(longitudeDifference / 2) *
      Math.sin(longitudeDifference / 2)

  const arc = 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value))

  return Math.round(earthRadiusMeters * arc)
}

export function openRouteInNavigator(latitude: number, longitude: number): void {
  const isAppleDevice = /iPad|iPhone|iPod/.test(navigator.userAgent)

  const navigationUrl = isAppleDevice
    ? `maps://?daddr=${latitude},${longitude}&dirflg=w`
    : `geo:${latitude},${longitude}?q=${latitude},${longitude}`

  window.location.href = navigationUrl
}

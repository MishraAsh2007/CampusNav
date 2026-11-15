import {isDisplayableImage} from './indoorModel';

export function availableMapStyles(floor) {
  return [
    {id: 'detailed', label: 'Detailed map', image: floor?.detailedImage},
    {id: 'simple', label: 'Simple map', vector: floor?.vectorPlan},
    {id: 'original', label: 'Original drawing', image: floor?.rawImage},
  ].filter(style => style.vector || isDisplayableImage(style.image));
}

/** Missing/broken backgrounds fall back without changing the route or camera. */
export function resolveMapStyle(floor, requested = 'detailed', failedImages = []) {
  const choices = availableMapStyles(floor).filter(style => !failedImages.includes(style.image));
  return choices.find(style => style.id === requested) || choices[0] || null;
}

import SimplifiedFloorPlan from './SimplifiedFloorPlan';
import InteractivePlan from './InteractivePlan';

/** Route segments, traced outlines and source image share the same pixel frame. */
export default function SourceRoutePlan({floor, route, active, image, zoom, onZoom, onImageError, mapStyle = 'detailed', focusStep = false}) {
  const segments = route.steps.filter(s => s.floor === floor.id && s.kind !== 'elevator' && s.pts?.length > 1);
  const step = route.steps[active];
  const focus = step?.floor === floor.id ? step.pts?.[0] : null;
  // ILC's original mosaics include whitespace. Crop the viewport, never transform
  // the geometry relative to the image. Other plans retain their full extent.
  const vector = mapStyle === 'simple' && floor.vectorPlan;
  let viewBox = floor.vectorPlan?.view_box.join(' ') || (floor.width === 1536 && floor.height === 1280
    ? '320 300 890 780' : `0 0 ${floor.width} ${floor.height}`);
  if (focusStep && focus && step.pts?.length) {
    const xs = step.pts.map(p => p[0]), ys = step.pts.map(p => p[1]);
    // Keep the named doorway visible when its threshold is part of this step.
    // Cropping a label halfway makes a focused phone view harder to orient.
    const entrance = floor.vectorPlan?.entrance;
    if (entrance && step.pts.some(p => Math.hypot(p[0] - entrance.x, p[1] - entrance.y) < 24)) {
      xs.push(entrance.label[0] - 95, entrance.label[0] + 95);
      ys.push(entrance.label[1] - 20, entrance.label[1] + 20);
    }
    const left = Math.min(...xs), top = Math.min(...ys);
    const width = Math.max(280, Math.max(...xs) - left + 120);
    const height = Math.max(260, Math.max(...ys) - top + 120);
    viewBox = `${(left + Math.max(...xs) - width) / 2} ${(top + Math.max(...ys) - height) / 2} ${width} ${height}`;
  }
  return <InteractivePlan key={`${floor.id}:${focusStep}:${focusStep ? active : ''}`} viewBox={viewBox} zoom={zoom} onZoom={onZoom}
    label={`${floor.label}: route on ${mapStyle === 'detailed' ? 'detailed map' : vector ? 'simplified room outlines' : 'original drawing'} from the published plan; marker shows selected step, not GPS`}>
    <g data-map-style={mapStyle}>
      {vector ? <SimplifiedFloorPlan plan={vector} /> : <image href={image} width={floor.width} height={floor.height} onError={onImageError} />}
    </g>
    {segments.map((s, i) => <g key={i}>
      <polyline points={s.pts.map(p => p.join(',')).join(' ')} fill="none" stroke="white" strokeWidth="9" strokeLinejoin="round" strokeLinecap="round" />
      <polyline points={s.pts.map(p => p.join(',')).join(' ')} fill="none" stroke={s === step ? '#0369a1' : '#059669'} strokeWidth="4" strokeLinejoin="round" strokeLinecap="round" />
    </g>)}
    {focus && <g><circle cx={focus[0]} cy={focus[1]} r="8" fill="#0369a1" stroke="white" strokeWidth="3" /><title>Selected instruction landmark; not live location</title></g>}
    {route.room.floor === floor.id && <circle cx={route.room.doorX} cy={route.room.doorY} r="7" fill="#be123c" stroke="white" strokeWidth="3"><title>Destination doorway approach</title></circle>}
  </InteractivePlan>;
}

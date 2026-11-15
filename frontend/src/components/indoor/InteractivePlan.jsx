import {useRef, useState} from 'react';
import {beginMapGesture, mapUnitsPerPixel, moveMapGesture} from './mapCamera';

/** A camera over the original plan coordinates, shared by image and route layers. */
export default function InteractivePlan({viewBox, zoom = 100, onZoom, label, children}) {
  const bounds = viewBox.split(/\s+/).map(Number);
  const [offset, setOffset] = useState({x: 0, y: 0});
  const [dragging, setDragging] = useState(false);
  const pointers = useRef(new Map());
  const gesture = useRef(null);
  const camera = useRef(null);
  camera.current = {...offset, zoom};
  const startGesture = element => {
    gesture.current = pointers.current.size ? beginMapGesture([...pointers.current.values()], bounds, element.getBoundingClientRect(), camera.current) : null;
    setDragging(pointers.current.size > 0);
  };
  const onPointerDown = event => {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.focus({preventScroll: true});
    event.currentTarget.setPointerCapture(event.pointerId);
    pointers.current.set(event.pointerId, {x: event.clientX, y: event.clientY});
    startGesture(event.currentTarget);
  };
  const onPointerMove = event => {
    if (!pointers.current.has(event.pointerId) || !gesture.current) return;
    pointers.current.set(event.pointerId, {x: event.clientX, y: event.clientY});
    const next = moveMapGesture(gesture.current, [...pointers.current.values()], bounds, event.currentTarget.getBoundingClientRect());
    camera.current = next;
    setOffset({x: next.x, y: next.y});
    onZoom?.(next.zoom);
  };
  const endPointer = event => {
    if (!pointers.current.delete(event.pointerId)) return;
    startGesture(event.currentTarget);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const onKeyDown = event => {
    const direction = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}[event.key];
    if (event.key === 'Home') {event.preventDefault(); setOffset({x: 0, y: 0}); onZoom?.(100);}
    if (!direction) return;
    event.preventDefault();
    const units = mapUnitsPerPixel(bounds, event.currentTarget.getBoundingClientRect(), zoom);
    setOffset(old => ({x: old.x + direction[0] * 60 * units, y: old.y + direction[1] * 60 * units}));
  };
  const width = bounds[2] * 100 / zoom, height = bounds[3] * 100 / zoom;
  const cameraBox = [bounds[0] + (bounds[2] - width) / 2 + offset.x,
    bounds[1] + (bounds[3] - height) / 2 + offset.y, width, height].join(' ');
  return <div className={`guide-plan-scroll${dragging ? ' is-dragging' : ''}`} tabIndex={0}
    role="region" aria-label="Floor plan: drag to pan, pinch to zoom. Arrow keys pan; Home resets the view."
    onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endPointer}
    onPointerCancel={endPointer} onLostPointerCapture={endPointer} onKeyDown={onKeyDown}>
    <svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label={label}
      viewBox={cameraBox} preserveAspectRatio="xMidYMid meet" style={{width: '100%', height: '100%', maxWidth: 'none'}}>{children}</svg>
  </div>;
}

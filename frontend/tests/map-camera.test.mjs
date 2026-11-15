import assert from 'node:assert/strict';
import {test} from 'node:test';
import {beginMapGesture, moveMapGesture} from '../src/components/indoor/mapCamera.js';

const bounds = [300, 300, 900, 800];
const viewport = {left: 10, top: 20, width: 300, height: 400};
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} != ${expected}`);

test('a finger can pan a fitted plan without zooming, including a letterboxed viewport', () => {
  const gesture = beginMapGesture([{x: 100, y: 120}], bounds, viewport, {x: 0, y: 0, zoom: 100});
  const moved = moveMapGesture(gesture, [{x: 140, y: 180}], bounds, viewport);
  assert.deepEqual(moved, {x: -120, y: -180, zoom: 100});
});

test('pinching keeps the touched landmark under the moving midpoint and clamps zoom', () => {
  const camera = {x: 25, y: -30, zoom: 100};
  const gesture = beginMapGesture([{x: 50, y: 150}, {x: 150, y: 150}], bounds, viewport, camera);
  const moved = moveMapGesture(gesture, [{x: 20, y: 190}, {x: 220, y: 190}], bounds, viewport);
  assert.equal(moved.zoom, 200);
  const anchorAfter = beginMapGesture([{x: 120, y: 190}], bounds, viewport, moved).anchor;
  close(anchorAfter.x, gesture.anchor.x);
  close(anchorAfter.y, gesture.anchor.y);
  assert.equal(moveMapGesture(gesture, [{x: -1000, y: 190}, {x: 1000, y: 190}], bounds, viewport).zoom, 300);
  assert.equal(moveMapGesture(gesture, [{x: 100, y: 190}, {x: 120, y: 190}], bounds, viewport).zoom, 100);
});

test('lifting one finger after a pinch continues as a drag without jumping', () => {
  const points = [{x: 20, y: 180}, {x: 220, y: 180}];
  const gesture = beginMapGesture([{x: 60, y: 180}, {x: 160, y: 180}], bounds, viewport, {x: 0, y: 0, zoom: 100});
  const pinched = moveMapGesture(gesture, points, bounds, viewport);
  const remaining = beginMapGesture(points.slice(0, 1), bounds, viewport, pinched);
  assert.deepEqual(moveMapGesture(remaining, points.slice(0, 1), bounds, viewport), pinched);
  const dragged = moveMapGesture(remaining, [{x: 40, y: 180}], bounds, viewport);
  close(dragged.x, pinched.x - 30);
  close(dragged.y, pinched.y);
  assert.equal(dragged.zoom, 200);
});

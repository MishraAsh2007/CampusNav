/**
 * Shared screen positions for the indoor views, so the 2D map, the 3D view and IndoorFlow's toolbar
 * line up and never cover the step panel.
 *
 * IndoorFlow measures the step panel and sets two CSS variables on its root:
 *   --indoor-panel-h      distance from the screen bottom to the panel's top edge
 *   --indoor-right-inset  the same when the panel spans the full width (phones), else 16px
 * Things on the bottom-left sit above the panel; the bottom-right control column (3D/2D button,
 * zoom) only has to clear it on phones.
 */
export const POS = {
  headerTop: 'max(12px, env(safe-area-inset-top, 0px))',
  toolbarTop: 'calc(env(safe-area-inset-top, 0px) + 64px)',
  noticeTop: 'calc(env(safe-area-inset-top, 0px) + 116px)',
  aboveLeft: 'calc(var(--indoor-panel-h, 16px) + 12px)',
  aboveRight: 'calc(var(--indoor-right-inset, 16px) + 12px)'
};

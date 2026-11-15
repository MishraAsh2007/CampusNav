import { useEffect, useRef } from 'react';

/**
 * 360° equirectangular photosphere using Pannellum (the engine pannellum-react wraps).
 * pannellum-react itself requires React 16 and fails `npm install` on this React 18 project.
 *
 * Props
 *   url       equirectangular image URL (must allow CORS; WebGL reads the pixels)
 *   yaw       direction to face, degrees (animated when it changes)
 *   onLoad    called when the image is shown
 *   onError   called with a message if it cannot be shown
 */
export default function PanoramaView({ url, yaw = 0, onLoad, onError }) {
  const el = useRef(null);
  const viewer = useRef(null);
  const cb = useRef({ onLoad, onError });
  cb.current = { onLoad, onError };

  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    (async () => {
      try {
        await Promise.all([import('pannellum'), import('pannellum/build/pannellum.css')]);
        if (cancelled || !el.current) return;
        if (!window.pannellum) throw new Error('Pannellum failed to load');
        const v = window.pannellum.viewer(el.current, {
          type: 'equirectangular',
          panorama: url,
          autoLoad: true,
          showControls: false,
          showFullscreenCtrl: false,
          compass: false,
          crossOrigin: 'anonymous',
          hfov: 105,
          yaw,
          mouseZoom: true,
          keyboardZoom: false
        });
        viewer.current = v;
        // Slow networks or blocked images: fall back instead of a spinner forever
        timer = window.setTimeout(() => !cancelled && cb.current.onError?.('The 360° photo took too long to load.'), 12000);
        v.on('load', () => {
          window.clearTimeout(timer);
          cb.current.onLoad?.();
        });
        v.on('error', (msg) => {
          window.clearTimeout(timer);
          cb.current.onError?.(typeof msg === 'string' ? msg : 'The 360° photo could not be loaded.');
        });
      } catch (e) {
        cb.current.onError?.(e?.message || 'The 360° viewer could not start.');
      }
    })();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      try {
        viewer.current?.destroy();
      } catch {
        /* already gone */
      }
      viewer.current = null;
    };
  }, [url]);

  useEffect(() => {
    try {
      viewer.current?.lookAt(0, yaw, 105, 900);
    } catch {
      /* viewer not ready yet */
    }
  }, [yaw]);

  return <div ref={el} className="absolute inset-0 h-full w-full" aria-label="360 degree photo of the route" role="img" />;
}

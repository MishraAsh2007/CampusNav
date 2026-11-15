export const GOOGLE_MAPS_KEY: string = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || '';
/** Advanced markers need a Map ID. DEMO_MAP_ID works for development; set your own for cloud styling. */
export const MAP_ID: string = import.meta.env.VITE_GOOGLE_MAPS_MAP_ID || 'DEMO_MAP_ID';
export const CAMPUS_CENTER: [number, number] = [
  parseFloat(import.meta.env.VITE_MAP_DEFAULT_LAT || '42.3903'),
  parseFloat(import.meta.env.VITE_MAP_DEFAULT_LNG || '-72.5275')
];

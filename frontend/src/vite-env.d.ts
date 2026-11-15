/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_GOOGLE_MAPS_API_KEY?: string;
  readonly VITE_GOOGLE_MAPS_MAP_ID?: string;
  readonly VITE_GEMINI_API_KEY?: string;
  readonly VITE_GEMINI_MODEL?: string;
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_ROUTING_API_URL?: string;
  readonly VITE_ROUTING_ENGINE?: 'auto' | 'local' | 'remote';
  readonly VITE_MAP_DEFAULT_LAT?: string;
  readonly VITE_MAP_DEFAULT_LNG?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface Window {
  gm_authFailure?: () => void;
}

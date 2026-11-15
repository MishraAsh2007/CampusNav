/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: '#1d1d1f',
          2: '#424245',
          3: '#6e6e73',
          4: '#8e8e93'
        },
        canvas: '#f5f5f7',
        hairline: 'rgba(0, 0, 0, 0.08)',
        brand: {
          DEFAULT: '#8f2d35',
          soft: '#f7ecec'
        },
        go: { DEFAULT: '#2a9d64', soft: '#e8f6ee', ink: '#1c6b45' },
        stop: { DEFAULT: '#e5484d', soft: '#fdecec', ink: '#a8262b' },
        warn: { DEFAULT: '#f0a020', soft: '#fdf4e3', ink: '#8a5a00' },
        lift: { DEFAULT: '#6e56cf', soft: '#f1eefc', ink: '#4b389a' },
        sky: { DEFAULT: '#0a84ff', soft: '#e8f2ff', ink: '#0758b4' }
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"SF Pro Text"', '"Segoe UI"', 'Roboto', 'sans-serif'],
        display: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"SF Pro Display"', '"Segoe UI"', 'sans-serif']
      },
      borderRadius: {
        '4xl': '1.75rem'
      },
      boxShadow: {
        float: '0 1px 1px rgba(0,0,0,0.03), 0 6px 24px -6px rgba(0,0,0,0.10)',
        lift: '0 2px 4px rgba(0,0,0,0.04), 0 18px 48px -12px rgba(0,0,0,0.18)',
        ring: '0 0 0 1px rgba(0,0,0,0.06)'
      },
      transitionTimingFunction: {
        soft: 'cubic-bezier(0.22, 1, 0.36, 1)'
      },
      keyframes: {
        rise: { from: { opacity: '0', transform: 'translateY(8px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        fade: { from: { opacity: '0' }, to: { opacity: '1' } },
        pop: { '0%': { transform: 'scale(0.96)', opacity: '0' }, '100%': { transform: 'scale(1)', opacity: '1' } },
        shimmer: { '0%': { backgroundPosition: '-200% 0' }, '100%': { backgroundPosition: '200% 0' } }
      },
      animation: {
        rise: 'rise 0.45s cubic-bezier(0.22, 1, 0.36, 1) both',
        fade: 'fade 0.3s ease-out both',
        pop: 'pop 0.28s cubic-bezier(0.22, 1, 0.36, 1) both',
        shimmer: 'shimmer 1.6s linear infinite'
      }
    }
  },
  plugins: []
};

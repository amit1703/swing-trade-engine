/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans:      ['"Inter"', 'system-ui', 'sans-serif'],
        mono:      ['"IBM Plex Mono"', 'monospace'],
        condensed: ['"Barlow Condensed"', 'sans-serif'],
      },
      borderRadius: {
        card: '12px',
        pill: '999px',
      },
      boxShadow: {
        card:    '0 4px 24px rgba(0,0,0,0.5)',
        cardHov: '0 6px 32px rgba(0,0,0,0.7)',
        glow:    '0 0 16px rgba(0,200,122,0.25)',
        glowRed: '0 0 16px rgba(255,45,85,0.25)',
      },
      colors: {
        t: {
          bg:          '#000000',
          surface:     '#0d0d0d',
          panel:       '#111111',
          card:        '#131313',
          cardBorder:  '#222222',
          border:      '#1e1e1e',
          borderLight: '#2a2a2a',
          text:        '#e0e0e0',
          muted:       '#555555',
          accent:      '#50d8f0',
          accentDim:   '#0d4050',
          go:          '#00c87a',
          goDim:       '#003d25',
          halt:        '#ff2d55',
          haltDim:     '#4a0015',
          blue:        '#4a9eff',
          blueDim:     '#0a1f3a',
          purple:      '#9B6EFF',
          pink:        '#FF6EC7',
        },
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        card: {
          DEFAULT: 'var(--card)',
          foreground: 'var(--card-foreground)',
        },
        primary: {
          DEFAULT: 'var(--primary)',
          foreground: 'var(--primary-foreground)',
        },
        secondary: {
          DEFAULT: 'var(--secondary)',
          foreground: 'var(--secondary-foreground)',
        },
        muted: {
          DEFAULT: 'var(--muted)',
          foreground: 'var(--muted-foreground)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          foreground: 'var(--accent-foreground)',
        },
        destructive: {
          DEFAULT: 'var(--destructive)',
          foreground: 'var(--destructive-foreground)',
        },
        border: 'var(--border)',
        input: 'var(--input)',
        ring: 'var(--ring)',
      },
      keyframes: {
        pulse_halt: { '0%, 100%': { opacity: '1' }, '50%': { opacity: '0.7' } },
        blink:      { '0%, 100%': { opacity: '1' }, '50%': { opacity: '0'   } },
        scanIn:     { '0%': { transform: 'translateY(-4px)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
        shimmer:    { '0%': { backgroundPosition: '-200% 0' }, '100%': { backgroundPosition: '200% 0' } },
        fadeUp:     { '0%': { transform: 'translateY(8px)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
      },
      animation: {
        pulse_halt: 'pulse_halt 1.4s ease-in-out infinite',
        blink:      'blink 1s step-end infinite',
        scanIn:     'scanIn 0.18s ease-out forwards',
        shimmer:    'shimmer 1.8s linear infinite',
        fadeUp:     'fadeUp 0.2s ease-out forwards',
      },
    },
  },
  plugins: [require('@tailwindcss/container-queries'), require('tailwindcss-animate')],
}

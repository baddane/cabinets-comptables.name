import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        green: {
          DEFAULT: '#0A7C5C',
          light:   '#12A87A',
          pale:    '#E6F5F0',
        },
        orange: {
          DEFAULT: '#F5622D',
          light:   '#FF8255',
          pale:    '#FFF0EB',
        },
        cream: '#FAF8F4',
        ink: {
          DEFAULT: '#1A1A2E',
          muted:   '#5A5A72',
          faint:   '#9898AA',
        },
        border: '#E8E6E0',
      },
      fontFamily: {
        sans:    ['var(--font-dm-sans)', 'system-ui', 'sans-serif'],
        display: ['var(--font-syne)',    'sans-serif'],
      },
      borderRadius: {
        '2xl': '16px',
        '3xl': '28px',
      },
      boxShadow: {
        sm: '0 2px 8px rgba(26,26,46,0.06)',
        md: '0 8px 32px rgba(26,26,46,0.10)',
        lg: '0 24px 64px rgba(26,26,46,0.14)',
      },
      animation: {
        'fade-up':  'fadeUp .7s cubic-bezier(.22,1,.36,1) both',
        'float':    'float 6s ease-in-out infinite',
        'pulse-ring': 'pulseRing 1.5s ease-out infinite',
      },
      keyframes: {
        fadeUp: {
          from: { opacity: '0', transform: 'translateY(24px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        float: {
          '0%,100%': { transform: 'translateY(0) rotate(0deg)' },
          '50%':     { transform: 'translateY(-10px) rotate(1deg)' },
        },
        pulseRing: {
          '0%':   { transform: 'scale(1)', opacity: '.6' },
          '100%': { transform: 'scale(1.5)', opacity: '0' },
        },
      },
    },
  },
  plugins: [],
}

export default config

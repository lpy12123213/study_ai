/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Premium Dark Theme Palette
        background: '#0f172a', // Slate 950
        surface: '#1e293b',    // Slate 800
        surfaceHighlight: '#334155', // Slate 700
        
        primary: {
          DEFAULT: '#8b5cf6', // Violet 500
          hover: '#7c3aed',   // Violet 600
          light: '#a78bfa',   // Violet 400
          glow: 'rgba(139, 92, 246, 0.5)'
        },
        secondary: {
          DEFAULT: '#10b981', // Emerald 500
          hover: '#059669',   // Emerald 600
        },
        accent: {
          DEFAULT: '#38bdf8', // Sky 400
          glow: 'rgba(56, 189, 248, 0.5)'
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.4s ease-out',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        }
      }
    },
  },
  plugins: [],
}

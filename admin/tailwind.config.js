/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        sidebar: {
          bg: '#1e293b',
          border: '#334155',
        },
        card: {
          bg: '#1e293b',
          border: '#334155',
        },
      },
    },
  },
  plugins: [],
};

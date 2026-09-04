/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        cyber: {
          bg: "#05070f",
          card: "rgba(13, 18, 36, 0.75)",
          border: "rgba(0, 240, 255, 0.2)",
          cyan: "#00f0ff",
          blue: "#3b82f6",
          purple: "#8b5cf6",
          pink: "#ec4899",
          neonGreen: "#10b981",
          gold: "#f59e0b"
        }
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'monospace'],
        sans: ['Inter', 'sans-serif'],
      }
    },
  },
  plugins: [],
}

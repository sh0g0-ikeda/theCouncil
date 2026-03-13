import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        board: {
          bg: "#f1e3cb",
          paper: "#fcf6ea",
          border: "#ad9a7b",
          ink: "#2b2218",
          muted: "#6b5d4d",
          accent: "#1f6c48",
          warn: "#8a3d2c"
        }
      },
      boxShadow: {
        board: "0 12px 30px rgba(64, 45, 19, 0.12)"
      }
    }
  },
  plugins: []
};

export default config;


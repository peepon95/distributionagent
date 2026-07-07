import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#FAF7F2",
        ink: "#211D16",
        tangerine: "#FF8A3D",
        blueberry: "#6C8CFF",
        bubblegum: "#FF9EC2",
      },
      fontFamily: {
        display: ["var(--font-display)", "sans-serif"],
        body: ["var(--font-body)", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(33,29,22,0.04), 0 8px 24px rgba(33,29,22,0.07)",
        lift: "0 2px 4px rgba(33,29,22,0.06), 0 16px 40px rgba(33,29,22,0.12)",
      },
      borderRadius: {
        card: "20px",
        big: "24px",
      },
    },
  },
  plugins: [],
};
export default config;

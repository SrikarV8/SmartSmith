/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Neutral graphite palette with one restrained copper accent
        ink: "#121212",
        coal: "#181818",
        iron: "#212121",
        steel: "#2e2e2e",
        ember: { DEFAULT: "#b08968", soft: "#b99677", deep: "#8a6a4e" },
        molten: "#d3b595",
        bone: "#ebe8e2",
        ash: "#a3a09a",
        smoke: "#76736d",
        baxa: { DEFAULT: "#6e6a78", deep: "#4a4752", light: "#a9a5b3" },
      },
      fontFamily: {
        display: ['"Figtree"', "ui-sans-serif", "system-ui", "sans-serif"],
        body: ['"Figtree"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"Figtree"', "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

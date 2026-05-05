/** @type {import("tailwindcss").Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        strong: "#16a34a",
        marginal: "#eab308",
        weak: "#f97316",
        nocov: "#dc2626",
      },
    },
  },
  plugins: [],
};

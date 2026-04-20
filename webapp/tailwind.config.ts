/** Vlessich Mini-App — Spotify-dark tokens (Design.txt). */
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surfaces
        "bg-base": "#121212",
        "bg-elevated": "#181818",
        "bg-mid": "#1f1f1f",
        "bg-card": "#252525",
        "bg-card-alt": "#272727",
        // Text
        "text-base": "#ffffff",
        "text-muted": "#b3b3b3",
        "text-subtle": "#cbcbcb",
        "text-bright": "#fdfdfd",
        // Borders
        "border-base": "#4d4d4d",
        "border-muted": "#7c7c7c",
        // Brand
        "brand-green": "#1ed760",
        "brand-green-border": "#1db954",
        // Semantic
        negative: "#f3727f",
        warning: "#ffa42b",
        announcement: "#539df5",
      },
      fontFamily: {
        sans: [
          "SpotifyMixUI",
          "Circular",
          "-apple-system",
          "BlinkMacSystemFont",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        title: [
          "SpotifyMixUITitle",
          "SpotifyMixUI",
          "Circular",
          "-apple-system",
          "sans-serif",
        ],
      },
      borderRadius: { pill: "9999px" },
      boxShadow: {
        elevated: "0 8px 24px rgba(0,0,0,0.5)",
        "card-inset":
          "rgb(18,18,18) 0px 1px 0px, rgb(124,124,124) 0px 0px 0px 1px inset",
      },
    },
  },
  plugins: [],
} satisfies Config;

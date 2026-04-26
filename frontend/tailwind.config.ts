import type { Config } from "tailwindcss";

export default {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        text: {
          primary: "var(--color-text-primary)",
          secondary: "var(--color-text-secondary)",
          tertiary: "var(--color-text-tertiary)",
          info: "var(--color-text-info)",
          danger: "var(--color-text-danger)",
        },
        bg: {
          primary: "var(--color-background-primary)",
          secondary: "var(--color-background-secondary)",
          tertiary: "var(--color-background-tertiary)",
          info: "var(--color-background-info)",
        },
        border: {
          tertiary: "var(--color-border-tertiary)",
          secondary: "var(--color-border-secondary)",
          info: "var(--color-border-info)",
        },
      },
      borderWidth: {
        hairline: "0.5px",
      },
      fontFamily: {
        sans: ["var(--font-archivo)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-brawler)", "ui-serif", "Georgia", "serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: {
        "2xs": ["10px", "14px"],
        "3xs": ["9px", "12px"],
      },
    },
  },
  plugins: [],
} satisfies Config;

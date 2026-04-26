import type { Metadata } from "next";
import { Archivo, Brawler, Geist_Mono } from "next/font/google";
import "./globals.css";

const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
  display: "swap",
});

const brawler = Brawler({
  variable: "--font-brawler",
  subsets: ["latin"],
  weight: "400",
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Polaris",
  description: "Hospital paging — priority triage and clinician dispatch",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${archivo.variable} ${brawler.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}

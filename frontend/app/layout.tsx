import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Rino",
  description: "Runs your repo's tests, triages the bugs, and suggests fixes you approve.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

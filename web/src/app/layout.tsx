import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MapleGuard — watches your immigration case",
  description:
    "MapleGuard watches your Canadian immigration case and surfaces one cited alert when a real IRCC change moves your standing. Every number is computed from the published grids and cited to source. Computed, not adjudicated.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

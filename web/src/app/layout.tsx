import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MapleGuard — Express Entry position",
  description:
    "Your Express Entry CRS, computed from the published IRCC grids and cited to source. Computed, not adjudicated.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

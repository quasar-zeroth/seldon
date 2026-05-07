import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "The Seldon Project",
  description: "Prediction intelligence mission control",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

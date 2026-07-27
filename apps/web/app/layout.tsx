import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { Fraunces, Source_Sans_3 } from "next/font/google";
import { Toaster } from "@/components/ui/sonner";
import { AppHeader } from "@/components/app-header";
import { cn } from "@/lib/utils";
import "./globals.css";

const display = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
});

const sans = Source_Sans_3({
  subsets: ["latin"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: "Housing Decision",
  description:
    "Multi-agent housing recommendations with explicit trade-offs for budget, commute, and neighborhood fit.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ClerkProvider>
      <html lang="en" className={cn(display.variable, sans.variable)}>
        <body className="min-h-screen font-sans antialiased">
          <div className="relative min-h-screen bg-[radial-gradient(ellipse_at_top,_#e8f0ea_0%,_#f7f4ef_45%,_#eef2f6_100%)]">
            <AppHeader />
            <main>{children}</main>
          </div>
          <Toaster richColors closeButton position="top-center" />
        </body>
      </html>
    </ClerkProvider>
  );
}

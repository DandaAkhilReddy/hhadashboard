import { AuthProvider } from "@/components/AuthProvider";
import { Toaster } from "@/components/Toast";
import { TopNav } from "@/components/TopNav";
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HHA Medicine — Operations Dashboard",
  description: "Exec leadership operations dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 antialiased">
        <AuthProvider>
          <TopNav />
          <main className="mx-auto max-w-[1600px] px-6 py-8">{children}</main>
          <Toaster />
        </AuthProvider>
      </body>
    </html>
  );
}

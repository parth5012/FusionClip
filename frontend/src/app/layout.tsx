import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'FusionClip Workspace',
  description: 'Self-hosted multimedia management and generation dashboard',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased min-h-screen bg-slate-950 text-slate-100">
        {children}
      </body>
    </html>
  );
}

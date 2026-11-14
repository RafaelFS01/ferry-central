import type { Metadata } from 'next';
import { IBM_Plex_Sans } from 'next/font/google';
import './globals.css';

const body = IBM_Plex_Sans({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--font-body' });

export const metadata: Metadata = {
  title: 'Dashboard Náutico — Central',
  description: 'Rastreamento cartográfico do ferry Salvador–Itaparica',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" className={body.variable}>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}

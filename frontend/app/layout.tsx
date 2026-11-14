import type { Metadata } from 'next';
import { JetBrains_Mono, SUSE } from 'next/font/google';
import './globals.css';

const sans = SUSE({ subsets: ['latin'], variable: '--font-suse' });
const mono = JetBrains_Mono({ subsets: ['latin'], variable: '--font-jetbrains' });

export const metadata: Metadata = {
  title: 'Dashboard Náutico — Central',
  description: 'Rastreamento cartográfico do ferry Salvador–Itaparica',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" className={`${sans.variable} ${mono.variable}`}>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}

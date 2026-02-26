import type { Metadata } from 'next'
import { Syne, DM_Sans } from 'next/font/google'
import './globals.css'
import Navigation from '@/components/layout/Navigation'
import Footer from '@/components/layout/Footer'

const syne = Syne({
  subsets: ['latin'],
  weight: ['400', '600', '700', '800'],
  variable: '--font-syne',
  display: 'swap',
})

const dmSans = DM_Sans({
  subsets: ['latin'],
  weight: ['300', '400', '500'],
  style: ['normal', 'italic'],
  variable: '--font-dm-sans',
  display: 'swap',
})

export const metadata: Metadata = {
  metadataBase: new URL('https://www.cabinets-comptables.name'),
  title: {
    default:  'Cabinets-Comptables.name — Annuaire Expert-Comptable France',
    template: '%s | Cabinets-Comptables.name',
  },
  description: 'Annuaire national des cabinets comptables et experts-comptables en France. Comparez avis, tarifs et spécialités. Devis gratuit.',
  robots: { index: true, follow: true },
  openGraph: {
    type: 'website',
    siteName: 'Cabinets-Comptables.name',
    locale: 'fr_FR',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="fr" className={`${syne.variable} ${dmSans.variable}`}>
      <body>
        <Navigation />
        {children}
        <Footer />
      </body>
    </html>
  )
}

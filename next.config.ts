import type { NextConfig } from 'next'

const config: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: '**.supabase.co' },
      { protocol: 'https', hostname: 'lh3.googleusercontent.com' },
      { protocol: 'https', hostname: '**.googleapis.com' },
    ],
  },
  // Redirections legacy (ancien site Python)
  async redirects() {
    return [
      {
        source: '/cabinet/:slug',
        destination: '/cabinets/:slug',
        permanent: true,
      },
    ]
  },
}

export default config

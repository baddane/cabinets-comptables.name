// ============================================================
// SUPABASE CLIENT + DATA FETCHING
// src/lib/supabase.ts
// ============================================================

import { createClient } from '@supabase/supabase-js'
import type {
  Cabinet, City, Specialty, Service, BlogPost,
  SearchFilters, SearchResult, SeoPage, LeadFormData,
} from '@/types'

// ——— Clients Supabase ———

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)

export const supabaseAdmin = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
)

// ============================================================
// CABINETS
// ============================================================

export async function getCabinet(slug: string): Promise<Cabinet | null> {
  const { data, error } = await supabase
    .from('cabinets')
    .select(`
      *,
      city:cities(*),
      specialties:cabinet_specialties(specialty:specialties(*)),
      services:cabinet_services(service:services(*)),
      softwares:cabinet_softwares(software:softwares(*)),
      pricing:cabinet_pricing(*),
      reviews(*)
    `)
    .eq('slug', slug)
    .in('status', ['active', 'premium'])
    .single()

  if (error || !data) return null

  return {
    ...data,
    specialties: data.specialties?.map((cs: any) => cs.specialty) || [],
    services:    data.services?.map((cs: any) => cs.service) || [],
    softwares:   data.softwares?.map((cs: any) => cs.software) || [],
  } as Cabinet
}

export async function searchCabinets(
  filters: SearchFilters,
  limit = 20,
  offset = 0
): Promise<SearchResult[]> {
  const { data, error } = await supabase.rpc('search_cabinets', {
    p_city_slug:      filters.city_slug || null,
    p_specialty_slug: filters.specialty_slug || null,
    p_service_slug:   filters.service_slug || null,
    p_query:          filters.query || null,
    p_limit:          limit,
    p_offset:         offset,
  })

  if (error) {
    console.error('searchCabinets error:', error)
    return []
  }
  return data || []
}

export async function getPremiumCabinets(citySlug?: string): Promise<Cabinet[]> {
  let query = supabase
    .from('cabinets')
    .select('*, city:cities(name, slug), pricing:cabinet_pricing(*)')
    .eq('is_premium', true)
    .eq('status', 'premium')

  if (citySlug) {
    query = query.eq('cities.slug', citySlug)
  }

  const { data } = await query.limit(6)
  return data || []
}

export async function getCabinetSlugs(): Promise<string[]> {
  const { data } = await supabaseAdmin
    .from('cabinets')
    .select('slug')
    .in('status', ['active', 'premium'])

  return data?.map((c) => c.slug) || []
}

// ============================================================
// VILLES
// ============================================================

export async function getCity(slug: string): Promise<City | null> {
  const { data } = await supabase
    .from('cities')
    .select('*, department:departments(*, region:regions(*))')
    .eq('slug', slug)
    .eq('is_active', true)
    .single()

  return data
}

export async function getAllCities(): Promise<City[]> {
  const { data } = await supabase.rpc('get_cities_with_counts')
  return data || []
}

export async function getCitySlugs(): Promise<string[]> {
  const { data } = await supabase
    .from('cities')
    .select('slug')
    .eq('is_active', true)

  return data?.map((c) => c.slug) || []
}

// ============================================================
// SPÉCIALITÉS
// ============================================================

export async function getSpecialties(): Promise<Specialty[]> {
  const { data } = await supabase
    .from('specialties')
    .select('*')
    .order('name')

  return data || []
}

export async function getSpecialty(slug: string): Promise<Specialty | null> {
  const { data } = await supabase
    .from('specialties')
    .select('*')
    .eq('slug', slug)
    .single()

  return data
}

// ============================================================
// BLOG
// ============================================================

export async function getBlogPosts(
  category?: string,
  limit = 10
): Promise<BlogPost[]> {
  let query = supabase
    .from('blog_posts')
    .select('*')
    .eq('status', 'published')
    .order('published_at', { ascending: false })
    .limit(limit)

  if (category) {
    query = query.eq('category', category)
  }

  const { data } = await query
  return data || []
}

export async function getBlogPost(slug: string): Promise<BlogPost | null> {
  const { data } = await supabase
    .from('blog_posts')
    .select('*')
    .eq('slug', slug)
    .eq('status', 'published')
    .single()

  return data
}

export async function getBlogSlugs(): Promise<string[]> {
  const { data } = await supabase
    .from('blog_posts')
    .select('slug')
    .eq('status', 'published')

  return data?.map((p) => p.slug) || []
}

// ============================================================
// PAGES SEO (ville × spécialité)
// ============================================================

export async function getSeoPage(
  citySlug: string,
  specialtySlug: string
): Promise<SeoPage | null> {
  const { data } = await supabase
    .from('seo_pages')
    .select('*, city:cities(*), specialty:specialties(*)')
    .eq('cities.slug', citySlug)
    .eq('specialties.slug', specialtySlug)
    .eq('is_active', true)
    .single()

  return data
}

// ============================================================
// LEADS
// ============================================================

export async function submitLead(formData: LeadFormData): Promise<boolean> {
  const { error } = await supabase
    .from('leads')
    .insert({
      ...formData,
      source_page: typeof window !== 'undefined' ? window.location.pathname : null,
    })

  return !error
}

// ============================================================
// AVIS
// ============================================================

export async function submitReview(reviewData: {
  cabinet_id: string
  author_name: string
  author_email: string
  author_type?: string
  rating: number
  rating_price?: number
  rating_communication?: number
  rating_reactivity?: number
  title?: string
  content?: string
}): Promise<boolean> {
  const { error } = await supabase
    .from('reviews')
    .insert({
      ...reviewData,
      is_published: false, // modération manuelle
    })

  return !error
}

// ============================================================
// ANALYTICS
// ============================================================

export async function trackCabinetView(cabinetId: string): Promise<void> {
  await supabase.from('cabinet_profile_views').insert({
    cabinet_id: cabinetId,
    session_id: getSessionId(),
  })
}

function getSessionId(): string {
  if (typeof window === 'undefined') return ''
  let sid = sessionStorage.getItem('sid')
  if (!sid) {
    sid = Math.random().toString(36).slice(2)
    sessionStorage.setItem('sid', sid)
  }
  return sid
}

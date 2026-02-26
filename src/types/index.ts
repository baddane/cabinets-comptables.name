// ============================================================
// TYPES TYPESCRIPT — cabinets-comptables.name
// ============================================================

export type CabinetStatus = 'pending' | 'active' | 'premium' | 'suspended'
export type CabinetSize   = 'solo' | 'small' | 'medium' | 'large'
export type LeadStatus    = 'new' | 'sent' | 'viewed' | 'contacted' | 'converted' | 'lost'
export type PostStatus    = 'draft' | 'published' | 'archived'

// ——— Géographie ———

export interface Region {
  id: string
  name: string
  slug: string
  created_at: string
}

export interface Department {
  id: string
  region_id: string
  name: string
  slug: string
  number: string
  region?: Region
}

export interface City {
  id: string
  department_id: string
  name: string
  slug: string
  postal_codes: string[]
  latitude: number | null
  longitude: number | null
  population: number | null
  seo_title: string | null
  seo_description: string | null
  seo_content: string | null
  is_active: boolean
  department?: Department
  cabinet_count?: number
}

// ——— Spécialités & Services ———

export interface Specialty {
  id: string
  name: string
  slug: string
  description: string | null
  icon: string | null
  seo_title: string | null
  seo_description: string | null
}

export interface Service {
  id: string
  name: string
  slug: string
  category: 'comptabilite' | 'fiscal' | 'social' | 'juridique' | 'conseil'
}

export interface Software {
  id: string
  name: string
  slug: string
  logo_url: string | null
}

// ——— Cabinet ———

export interface CabinetPricing {
  id: string
  cabinet_id: string
  price_monthly_min: number | null
  price_monthly_max: number | null
  price_tpe_min: number | null
  price_tpe_max: number | null
  price_freelance_min: number | null
  price_freelance_max: number | null
  price_pme_min: number | null
  price_pme_max: number | null
  hourly_rate: number | null
  free_consultation: boolean
  remote_available: boolean
}

export interface CabinetRating {
  cabinet_id: string
  review_count: number
  avg_rating: number
  avg_rating_price: number | null
  avg_rating_communication: number | null
  avg_rating_reactivity: number | null
}

export interface Review {
  id: string
  cabinet_id: string
  author_name: string
  author_type: string | null
  rating: number
  rating_price: number | null
  rating_communication: number | null
  rating_reactivity: number | null
  title: string | null
  content: string | null
  is_verified: boolean
  is_published: boolean
  created_at: string
}

export interface Cabinet {
  id: string
  name: string
  slug: string
  description: string | null
  short_description: string | null
  city_id: string | null
  address: string | null
  postal_code: string | null
  latitude: number | null
  longitude: number | null
  phone: string | null
  email: string | null
  website: string | null
  logo_url: string | null
  cover_url: string | null
  founded_year: number | null
  size: CabinetSize
  employee_count: number | null
  oec_registered: boolean
  oec_number: string | null
  status: CabinetStatus
  is_premium: boolean
  premium_since: string | null
  premium_until: string | null
  seo_title: string | null
  seo_description: string | null
  source: string
  verified_at: string | null
  created_at: string
  updated_at: string
  // Relations jointes
  city?: City
  specialties?: Specialty[]
  services?: Service[]
  softwares?: Software[]
  pricing?: CabinetPricing | null
  rating?: CabinetRating | null
  reviews?: Review[]
}

// ——— Leads ———

export interface Lead {
  id: string
  cabinet_id: string | null
  city_id: string | null
  specialty_id: string | null
  first_name: string
  last_name: string
  email: string
  phone: string | null
  company_name: string | null
  company_type: string | null
  revenue_range: string | null
  message: string | null
  services_needed: string[]
  urgency: 'immediate' | '1month' | '3months' | null
  current_accountant: boolean | null
  source_page: string | null
  status: LeadStatus
  price_charged: number | null
  sent_at: string | null
  created_at: string
}

export interface LeadFormData {
  first_name: string
  last_name: string
  email: string
  phone?: string
  company_name?: string
  company_type?: string
  revenue_range?: string
  message?: string
  services_needed?: string[]
  urgency?: 'immediate' | '1month' | '3months'
  current_accountant?: boolean
  cabinet_id?: string
  city_id?: string
  specialty_id?: string
}

// ——— Blog ———

export interface BlogPost {
  id: string
  title: string
  slug: string
  excerpt: string | null
  content: string | null
  cover_url: string | null
  category: string | null
  tags: string[]
  seo_title: string | null
  seo_description: string | null
  author_name: string
  author_avatar: string | null
  status: PostStatus
  published_at: string | null
  read_time_minutes: number | null
  view_count: number
  created_at: string
}

// ——— Compte Cabinet ———

export interface CabinetAccount {
  id: string
  cabinet_id: string
  role: 'owner' | 'collaborator'
  subscription_plan: 'free' | 'premium' | 'premium_plus'
  subscription_start: string | null
  subscription_end: string | null
  stripe_customer_id: string | null
  email_notifications: boolean
  lead_notifications: boolean
  created_at: string
  cabinet?: Cabinet
}

// ——— Pages SEO ———

export interface SeoPage {
  id: string
  city_id: string
  specialty_id: string
  seo_title: string | null
  seo_description: string | null
  intro_content: string | null
  faq: Array<{ q: string; a: string }>
  is_active: boolean
  city?: City
  specialty?: Specialty
}

// ——— Résultats de recherche ———

export interface SearchResult {
  id: string
  name: string
  slug: string
  short_description: string | null
  address: string | null
  city_name: string
  city_slug: string
  logo_url: string | null
  is_premium: boolean
  avg_rating: number
  review_count: number
  specialties: string[]
  services: string[]
}

export interface SearchFilters {
  city_slug?: string
  specialty_slug?: string
  service_slug?: string
  query?: string
  price_max?: number
  remote_only?: boolean
  free_consultation?: boolean
  oec_registered?: boolean
}

// ——— Dashboard ———

export interface DashboardStats {
  total_views: number
  views_this_month: number
  total_leads: number
  leads_this_month: number
  profile_completeness: number
  subscription_plan: string
  subscription_end: string | null
}

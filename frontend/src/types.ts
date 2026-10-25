// Mirrors backend/app/schemas.py. Keep the two in sync when the API changes.
// Dates are ISO strings in UTC (they end with "Z").

export interface Option {
  id: string
  label: string
}

export interface Metrics {
  // null means the platform does not give us this number (not the same as 0)
  views: number | null
  likes: number | null
  comments: number | null
  shares: number | null
}

export interface Label {
  topic: string | null
  hook_type: string | null
  hook_text: string | null
  cta: string | null
  confidence: number | null
  labeler: string
}

export interface Score {
  score: number
  rank_in_platform: number | null
  engagement_rate: number | null
  outperformance: number | null
  adjusted_engagement: number | null
  reason: string | null
}

// us | likely_us | probable_us | unverified | non_us, plus the proof behind it
export interface Location {
  status: string
  evidence: string | null
}

export interface Account {
  platform: string
  handle: string
  name: string
  url: string | null
  followers: number | null
  location: Location
}

export interface PostCreator {
  id: number
  platform: string
  name: string
  handle: string
  followers: number | null
  competitor_id: number | null // null for hashtag posts: their author is unknown
}

export interface Post {
  id: number
  platform: string
  url: string
  title: string | null
  text_preview: string | null
  published_at: string | null
  format: string | null
  thumbnail_url: string | null
  creator: PostCreator
  metrics: Metrics
  label: Label | null
  score: Score
  location: Location
}

export interface PostsPage {
  window: number
  items: Post[]
  total: number
  limit: number
  offset: number
  too_new: number
}

export interface BestPost {
  id: number
  url: string
  title: string | null
  score: number | null
}

export interface Competitor {
  id: number
  name: string
  kind: string
  website: string | null
  status: string
  rank: number | null
  score: number | null
  posts_count: number
  consistency: number | null
  low_sample: boolean
  top_topic: string | null
  top_hook: string | null
  best_post: BestPost | null
  accounts: Account[]
}

export interface CompetitorsPage {
  window: number
  items: Competitor[]
  total: number
  hidden_low_sample: number
}

export interface WindowScore {
  window: number
  score: number
  posts_count: number
  consistency: number | null
  low_sample: boolean
}

export interface CompetitorDetail {
  window: number
  competitor: Competitor
  scores_by_window: WindowScore[]
  top_posts: Post[]
}

export interface InsightGroup {
  value: string
  label: string
  count: number
  avg_score: number
  avg_engagement: number
}

export interface Insights {
  window: number
  group_by: string
  platform: string | null
  groups: InsightGroup[]
  hidden_groups: number
  hidden_posts: number
  total_posts: number
  min_group_size: number
}

export interface PlatformInfo {
  id: string
  label: string
  enabled: boolean // keys are set in .env
  posts: number
}

export interface Taxonomy {
  version: number
  topics: Option[]
  hooks: Option[]
  ctas: Option[]
  formats: Option[]
}

export interface Thresholds {
  strong_score: number
  good_score: number
  min_group_size: number
  min_engagement_to_rank: number
  min_post_age_hours: number
  min_posts_by_window: Record<string, number>
}

export interface Meta {
  windows: number[]
  default_window: number
  platforms: PlatformInfo[]
  taxonomy: Taxonomy
  thresholds: Thresholds
  last_updated: string | null
  counts: {
    competitors: number
    posts: number
    labeled_posts: number
    ranked_posts: number
  }
}

export interface Run {
  id: number
  kind: string
  platform: string | null
  status: string
  items_ok: number
  items_failed: number
  quota_used: number
  message: string | null
  started_at: string
  finished_at: string | null
}

export interface Keyword {
  id: number
  term: string
  platform: string | null
  active: boolean
}

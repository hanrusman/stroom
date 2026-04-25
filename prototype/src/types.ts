export interface Article {
  id: string;
  type: 'Essay' | 'Analysis' | 'Quote' | 'Video' | 'Visual Essay';
  title: string;
  excerpt: string;
  author: string;
  readTime?: string;
  image?: string;
  authorHandle?: string;
  date?: string;
  category?: string;
  quote?: string;
}

export interface DeepDive {
  id: string;
  label: string;
  title: string;
  description: string;
  footerLabel: string;
  type: 'transcript' | 'archive';
}

export interface ShortForm {
  id: string;
  author: string;
  handle: string;
  avatar: string;
  content: string;
  time: string;
  topic: string;
  isSpecial?: boolean;
}

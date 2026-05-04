/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { motion } from 'motion/react';
import { 
  Search, 
  User, 
  ArrowRight, 
  Headphones, 
  History, 
  PlayCircle, 
  LayoutGrid,
  Library,
  Bookmark,
  Menu
} from 'lucide-react';
import { CURRENT_FLOW, DEEP_DIVES, SHORT_FORM } from './data';
import { Article, DeepDive, ShortForm as ShortFormType } from './types';

const NavItem = ({ 
  name, 
  active, 
  avatarOffset 
}: { 
  name: string; 
  active?: boolean; 
  avatarOffset: { top: number; left: number };
}) => (
  <a className="flex items-center gap-3 text-brand-ink group relative hover:opacity-80 transition-opacity" href="#">
    <div className="w-10 h-10 rounded-lg overflow-hidden relative shrink-0 shadow-sm border border-brand-ink/5">
      <img 
        src="https://lh3.googleusercontent.com/aida/ADBb0ug-uh55IPMzoyTOZdTR0k75AeIeMpV4lL69RcISbGllcVkC_3SgLJ9p-2-Ti5NPZm9P7ZS4lOop17nfHA4jtn9e59q8DBel54U6zx4W9eyZZrRLnEy0_LCoVHJkGcOUVqtPLL8PI0EgeI7hMFfZRy_wiDKuDFIzUSI1yToI7J-W3h-p0drjdfLc-1MtRfH4zI3NjRgQuWJRx6MvTc7kd4c-HYxlRVgGYTuLPwHNaePqBiXTZc9VRwt6qaEqhSjSV7deBFmbafU4ww" 
        className="absolute" 
        style={{ 
          top: avatarOffset.top, 
          left: avatarOffset.left, 
          width: '1000px', 
          maxWidth: 'none' 
        }} 
        alt={name} 
      />
    </div>
    <span className="hidden xl:block text-sm font-medium tracking-tight text-stone-700 whitespace-nowrap">{name}</span>
    {active && (
      <motion.div 
        layoutId="nav-underline"
        className="absolute -bottom-6 left-0 right-0 h-0.5 bg-brand-blue" 
      />
    )}
  </a>
);

const FilterButton = ({ label, active }: { label: string; active?: boolean }) => {
  return (
    <button className={`px-6 py-2.5 rounded-full text-[13px] font-medium whitespace-nowrap shrink-0 transition-all ${
      active 
        ? 'bg-[#1a3a5f] text-white shadow-sm' 
        : 'bg-[#f5f5f5] hover:bg-stone-200 text-stone-600'
    }`}>
      {label}
    </button>
  );
};

interface ArticleCardProps {
  key?: React.Key;
  article: Article;
}

const ArticleCard = ({ article }: ArticleCardProps) => {
  const isQuote = article.type === 'Quote';
  const isVideo = article.type === 'Video';
  const isVisualEssay = article.type === 'Visual Essay';

  return (
    <motion.article 
      initial={{ opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      className="snap-start shrink-0 w-[85vw] md:w-[400px] flex flex-col gap-4 group cursor-pointer"
    >
      <div className={`w-full aspect-[4/3] rounded-3xl overflow-hidden relative ${isQuote ? 'bg-gradient-to-br from-brand-surface to-brand-surface-low flex items-center justify-center p-8 text-center' : 'bg-brand-surface'}`}>
        {!isQuote && article.image && (
          <img 
            src={article.image} 
            alt={article.title}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700 ease-out" 
          />
        )}
        
        {isQuote && (
          <blockquote className="font-serif text-3xl italic leading-snug text-brand-ink tracking-tight px-10">
            {article.quote}
          </blockquote>
        )}

        <div className={`absolute top-4 left-4 flex items-center gap-1.5 px-3 py-1 rounded-full text-[9px] font-bold uppercase tracking-[0.2em] backdrop-blur-md ${isVideo ? 'bg-brand-accent text-white' : 'bg-white/90 text-brand-ink shadow-sm'}`}>
          {isVideo && <PlayCircle size={10} />}
          {isVisualEssay && <Library size={10} />}
          {article.type}
        </div>
      </div>

      <div className="flex flex-col gap-2 px-2">
        <h3 className="font-serif font-semibold text-2xl text-brand-ink group-hover:text-brand-accent transition-colors line-clamp-2 leading-tight tracking-tight">
          {article.title}
        </h3>
        <p className="text-brand-ink/70 line-clamp-2 text-sm leading-relaxed font-light">
          {article.excerpt}
        </p>
        <div className="text-brand-ink/40 mt-2 text-[9px] font-bold uppercase tracking-widest flex items-center gap-2">
          <span>{article.author}</span>
          {article.readTime && (
            <>
              <span className="opacity-30">·</span>
              <span>{article.readTime}</span>
            </>
          )}
        </div>
      </div>
    </motion.article>
  );
};

interface DeepDiveCardProps {
  key?: React.Key;
  item: DeepDive;
}

const DeepDiveCard = ({ item }: DeepDiveCardProps) => (
  <motion.article 
    initial={{ opacity: 0, x: 20 }}
    whileInView={{ opacity: 1, x: 0 }}
    viewport={{ once: true }}
    className={`snap-start shrink-0 w-[85vw] md:w-[600px] rounded-3xl p-8 md:p-12 flex flex-col justify-between group transition-all duration-500 cursor-pointer ${item.type === 'transcript' ? 'bg-brand-surface-low hover:bg-brand-surface' : 'bg-brand-accent/[0.02] border border-brand-accent/10 hover:bg-brand-accent/[0.04]'}`}
  >
    <div>
      <div className="text-[10px] font-bold text-brand-accent uppercase tracking-[0.2em] mb-6">
        {item.label}
      </div>
      <h3 className="font-serif text-4xl md:text-5xl text-brand-ink mb-6 leading-tight group-hover:text-brand-accent transition-colors tracking-tight">
        {item.title}
      </h3>
      <p className="text-lg text-brand-ink/70 mb-8 line-clamp-3 leading-relaxed font-light">
        {item.description}
      </p>
    </div>
    <div className="flex items-center gap-4 border-t border-brand-ink/10 pt-6">
      <div className={`w-10 h-10 rounded-full flex items-center justify-center ${item.type === 'transcript' ? 'bg-brand-ink/5' : 'bg-brand-accent/10'}`}>
        {item.type === 'transcript' ? <Headphones size={18} className="text-brand-ink/60" /> : <History size={18} className="text-brand-accent" />}
      </div>
      <div className="text-[10px] font-bold uppercase tracking-widest text-brand-ink/40 italic">
        {item.footerLabel}
      </div>
    </div>
  </motion.article>
);

interface ShortFormCardProps {
  key?: React.Key;
  item: ShortFormType;
}

const ShortFormCard = ({ item }: ShortFormCardProps) => (
  <motion.article 
    initial={{ opacity: 0, scale: 0.95 }}
    whileInView={{ opacity: 1, scale: 1 }}
    viewport={{ once: true }}
    className={`snap-start shrink-0 w-[75vw] md:w-[320px] rounded-3xl p-6 flex flex-col gap-4 group transition-all duration-300 border cursor-pointer ${item.isSpecial ? 'bg-brand-green-tint border-brand-blue/10 hover:shadow-md' : 'bg-brand-surface border-brand-ink/5 hover:border-brand-ink/10 hover:shadow-sm'}`}
  >
    <div className="flex items-center gap-3">
      {item.avatar ? (
        <img src={item.avatar} className="w-10 h-10 rounded-full border border-brand-ink/10" alt={item.author} />
      ) : (
        <div className="w-10 h-10 rounded-full bg-brand-accent flex items-center justify-center text-white font-serif italic text-lg">
          {item.author[0]}
        </div>
      )}
      <div>
        <div className="text-xs font-bold text-brand-ink leading-none mb-1">{item.author}</div>
        <div className="text-[9px] font-mono text-brand-accent uppercase tracking-widest">{item.handle}</div>
      </div>
    </div>
    <p className={`text-sm leading-relaxed text-brand-ink/80 line-clamp-4 font-light ${item.content.startsWith('"') ? 'italic font-serif text-base' : ''}`}>
      {item.content}
    </p>
    <div className="text-[10px] font-bold uppercase tracking-[0.1em] text-brand-ink/30 flex items-center gap-2 mt-auto pt-2 border-t border-brand-ink/5">
      <span>{item.time}</span>
      <span className="opacity-30">·</span>
      <span className="text-brand-accent">{item.topic}</span>
    </div>
  </motion.article>
);

export default function App() {
  return (
    <div className="min-h-screen relative selection:bg-brand-blue selection:text-white">
      {/* Decorative background blobs */}
      <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden opacity-40">
        <div className="absolute top-[-10%] left-[-10%] w-[60vw] h-[614px] bg-brand-blue/5 rounded-[40%_60%_70%_30%/40%_50%_60%_50%] blur-3xl transform rotate-12" />
        <div className="absolute top-[20%] right-[-20%] w-[70vw] h-[819px] bg-brand-blue/[0.03] rounded-[60%_40%_30%_70%/50%_40%_60%_50%] blur-3xl transform -rotate-12" />
        
        <svg className="absolute inset-0 w-full h-full opacity-5" viewBox="0 0 100 100" preserveAspectRatio="none">
          <path d="M0,20 Q25,30 50,20 T100,20" fill="none" stroke="currentColor" strokeWidth="0.1" />
          <path d="M0,40 Q30,50 60,30 T100,40" fill="none" stroke="currentColor" strokeWidth="0.05" />
          <path d="M0,70 Q40,60 70,80 T100,60" fill="none" stroke="currentColor" strokeWidth="0.08" />
        </svg>
      </div>

      <nav className="sticky top-0 z-40 bg-brand-cream/95 backdrop-blur-md w-full border-b border-stone-200">
        <div className="flex justify-between items-center px-6 md:px-12 py-6 w-full max-w-screen-2xl mx-auto">
          <div className="text-3xl font-serif text-brand-ink tracking-tight flex items-center gap-3">
             <div className="w-10 h-10 overflow-hidden relative rounded-lg border border-brand-ink/5 shadow-sm">
               <img 
                src="https://lh3.googleusercontent.com/aida/ADBb0ug-uh55IPMzoyTOZdTR0k75AeIeMpV4lL69RcISbGllcVkC_3SgLJ9p-2-Ti5NPZm9P7ZS4lOop17nfHA4jtn9e59q8DBel54U6zx4W9eyZZrRLnEy0_LCoVHJkGcOUVqtPLL8PI0EgeI7hMFfZRy_wiDKuDFIzUSI1yToI7J-W3h-p0drjdfLc-1MtRfH4zI3NjRgQuWJRx6MvTc7kd4c-HYxlRVgGYTuLPwHNaePqBiXTZc9VRwt6qaEqhSjSV7deBFmbafU4ww" 
                className="absolute"
                style={{ clipPath: 'inset(45px 820px 920px 75px)', transform: 'scale(3.4)', top: '-110px', left: '-20px' }}
                alt="Stroom Logo"
               />
             </div>
             <span className="pt-1 font-serif italic font-medium text-stone-800">Stroom</span>
          </div>
          
          <div className="hidden md:flex gap-8 lg:gap-14 items-center">
            <NavItem 
              name="Huygens" 
              avatarOffset={{ top: -45, left: -360 }}
            />
            <NavItem 
              name="Spinoza" 
              avatarOffset={{ top: -45, left: -505 }}
            />
            <NavItem 
              name="v Leeuwenhoek" 
              active 
              avatarOffset={{ top: -45, left: -645 }}
            />
            <NavItem 
              name="Hertz" 
              avatarOffset={{ top: -45, left: -825 }}
            />
          </div>

          <div className="flex gap-8 items-center text-stone-400">
            <button className="hover:text-[#1a3a5f] transition-colors"><Search size={20} strokeWidth={2.5} /></button>
            <button className="hover:text-[#1a3a5f] transition-colors"><User size={20} strokeWidth={2.5} /></button>
          </div>
        </div>
      </nav>

      <main className="relative z-10 w-full max-w-screen-2xl mx-auto px-6 md:px-12 pb-32 pt-10">
        <section className="mb-20 space-y-8">
          <div className="flex items-center gap-4 overflow-x-auto hide-scrollbar pb-1">
            <span className="text-[12px] font-bold text-stone-400 uppercase tracking-[0.25em] mr-6 shrink-0">Topics</span>
            <FilterButton label="All Streams" active />
            <FilterButton label="Geopolitics" />
            <FilterButton label="Techno-Optimism" />
            <FilterButton label="Urbanism" />
            <FilterButton label="Climate Anthropology" />
            <FilterButton label="Economic Theory" />
          </div>
          
          <div className="flex items-center gap-4 overflow-x-auto hide-scrollbar pb-1">
            <span className="text-[12px] font-bold text-stone-400 uppercase tracking-[0.25em] mr-6 shrink-0">Media</span>
            <FilterButton label="Any Format" />
            <FilterButton label="Essays" active />
            <FilterButton label="Transcripts" />
            <FilterButton label="Data Visualizations" />
          </div>

          <div className="flex items-center gap-4 overflow-x-auto hide-scrollbar pb-1">
            <span className="text-[12px] font-bold text-stone-400 uppercase tracking-[0.25em] mr-6 shrink-0">Sources</span>
            <FilterButton label="Curated Only" />
            <FilterButton label="Primary Journals" />
            <FilterButton label="Independent Scholars" active />
            <FilterButton label="University Presses" />
          </div>
        </section>

        <section className="mb-24">
          <div className="flex justify-between items-end mb-10">
            <h2 className="font-serif text-3xl md:text-5xl text-brand-ink font-light tracking-tight leading-none">Current Flow</h2>
            <a className="text-[10px] font-bold text-brand-accent hover:opacity-70 transition-opacity flex items-center gap-1.5 uppercase tracking-[0.2em]" href="#">
              View All <ArrowRight size={12} />
            </a>
          </div>
          
          <div className="flex overflow-x-auto hide-scrollbar gap-8 pb-12 -mx-6 px-6 md:-mx-12 md:px-12 snap-x">
            {CURRENT_FLOW.map(article => (
              <ArticleCard key={article.id} article={article} />
            ))}
          </div>
        </section>

        <section className="mb-24">
          <div className="flex justify-between items-end mb-10 border-b border-brand-ink/10 pb-6">
            <h2 className="font-serif text-3xl md:text-4xl text-brand-ink font-semibold">Deep Dives</h2>
          </div>
          <div className="flex overflow-x-auto hide-scrollbar gap-10 pb-8 -mx-6 px-6 md:-mx-12 md:px-12 snap-x">
            {DEEP_DIVES.map(item => (
              <DeepDiveCard key={item.id} item={item} />
            ))}
          </div>
        </section>

        <section className="mb-12">
          <div className="flex justify-between items-end mb-10 border-b border-brand-ink/10 pb-6">
            <h2 className="font-serif text-3xl md:text-4xl text-brand-ink font-semibold">Short-form</h2>
            <a className="text-xs font-bold text-brand-blue hover:opacity-70 transition-opacity flex items-center gap-1.5 uppercase tracking-widest" href="#">
              View Stream <ArrowRight size={14} />
            </a>
          </div>
          <div className="flex overflow-x-auto hide-scrollbar gap-6 pb-12 -mx-6 px-6 md:-mx-12 md:px-12 snap-x">
            {SHORT_FORM.map(item => (
              <ShortFormCard key={item.id} item={item} />
            ))}
          </div>
        </section>
      </main>

      {/* Bottom Nav for Mobile */}
      <nav className="md:hidden fixed bottom-0 left-0 w-full z-50 flex justify-around items-center h-20 pb-safe px-4 bg-brand-cream/90 backdrop-blur-lg border-t border-brand-ink/5">
        <button className="flex flex-col items-center justify-center text-brand-blue w-full h-full">
          <LayoutGrid size={20} className="mb-1" />
          <span className="text-[8px] font-bold uppercase tracking-[0.2em] font-mono">Topics</span>
        </button>
        <button className="flex flex-col items-center justify-center text-brand-ink/30 w-full h-full">
          <div className="relative">
            <PlayCircle size={20} className="mb-1" />
          </div>
          <span className="text-[8px] font-bold uppercase tracking-[0.2em] font-mono">Media</span>
        </button>
        <button className="flex flex-col items-center justify-center text-brand-ink/30 w-full h-full">
          <Library size={20} className="mb-1" />
          <span className="text-[8px] font-bold uppercase tracking-[0.2em] font-mono">Sources</span>
        </button>
        <button className="flex flex-col items-center justify-center text-brand-ink/30 w-full h-full">
          <Bookmark size={20} className="mb-1" />
          <span className="text-[8px] font-bold uppercase tracking-[0.2em] font-mono">Saved</span>
        </button>
      </nav>
    </div>
  );
}

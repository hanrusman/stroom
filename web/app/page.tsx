import React from 'react';
import { Sparkles, BrainCircuit, ExternalLink, Clock, Save, ListTodo } from 'lucide-react';

export default function Stream() {
  const MOCK_ITEMS = [
    {
      id: "1",
      title: "Why AI Agents are the Next Frontier",
      type: "youtube",
      source: "Lex Fridman Podcast",
      time: "2 hours ago",
      summary: "A deep dive into how specialized AI agents will replace monolithic models for complex tasks, chaining reasoning steps organically.",
      insights: [
        "Monolithic models struggle with task switching without prompt degradation.",
        "Agentic workflows reduce errors by 40% in coding benchmarks."
      ]
    },
    {
      id: "2",
      title: "The Architecture of Tomorrow",
      type: "rss",
      source: "Hacker News",
      time: "5 hours ago",
      summary: "Modern web architecture is shifting back to server-side rendering for performance, leaving SPAs for highly interactive dashboards.",
      insights: [
        "RSC (React Server Components) ship zero JavaScript to the client.",
        "Latency is the new bottleneck, not bandwidth."
      ]
    }
  ];

  return (
    <div className="max-w-4xl mx-auto z-10 relative">
      <div className="flex flex-col md:flex-row md:items-center justify-between mb-10 gap-4">
        <div>
          <h2 className="text-3xl md:text-4xl font-extrabold tracking-tight mb-2">Jouw Stroom</h2>
          <p className="text-secondary text-lg">Samengevatte inzichten, klaar om te verkennen.</p>
        </div>
        
        <div className="glass px-4 py-2 rounded-full inline-flex items-center gap-2 border border-white/10 shadow-lg w-max">
          <BrainCircuit className="w-4 h-4 text-primary" />
          <span className="text-sm font-medium">12 processed. 0 in queue.</span>
        </div>
      </div>

      <div className="grid gap-6">
        {MOCK_ITEMS.map((item) => (
          <article key={item.id} className="glass p-6 md:p-8 rounded-2xl shadow-[0_8px_30px_rgb(0,0,0,0.12)] border border-white/5 transition-all duration-500 hover:shadow-[0_8px_30px_rgb(59,130,246,0.15)] group relative overflow-hidden">
            <div className="absolute top-0 left-0 w-1 h-full bg-gradient-to-b from-primary to-accent opacity-0 group-hover:opacity-100 transition-opacity duration-300"></div>
            
            <header className="flex flex-wrap items-start justify-between gap-4 mb-4">
              <div>
                <div className="flex items-center gap-3 mb-2 text-sm">
                  <span className="bg-primary/20 text-primary px-2.5 py-1 rounded-md font-semibold tracking-wide uppercase text-xs">
                    {item.type}
                  </span>
                  <span className="text-secondary font-medium">{item.source}</span>
                  <div className="flex items-center text-secondary/60 text-xs">
                    <Clock className="w-3 h-3 mr-1" /> {item.time}
                  </div>
                </div>
                <h3 className="text-xl md:text-2xl font-bold leading-tight group-hover:text-primary transition-colors">{item.title}</h3>
              </div>
              <button className="text-secondary hover:text-white transition-colors bg-white/5 p-2 rounded-xl">
                <ExternalLink className="w-5 h-5" />
              </button>
            </header>

            <p className="text-gray-300 text-base md:text-lg leading-relaxed mb-6">
              {item.summary}
            </p>

            <div className="bg-background/40 p-5 rounded-xl border border-white/5">
              <h4 className="flex items-center gap-2 font-bold mb-3 text-sm uppercase tracking-wider text-accent">
                <Sparkles className="w-4 h-4" /> Inzichten
              </h4>
              <ul className="space-y-4">
                {item.insights.map((insight, idx) => (
                  <li key={idx} className="flex gap-3 text-gray-200">
                    <span className="w-1.5 h-1.5 rounded-full bg-accent mt-2 flex-shrink-0"></span>
                    <p className="leading-snug flex-1">{insight}</p>
                    
                    {/* Action Buttons for each insight */}
                    <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity translate-x-4 group-hover:translate-x-0 duration-300">
                      <button title="Save to Obsidian" className="p-1.5 text-secondary hover:text-primary hover:bg-primary/10 rounded-lg transition-colors">
                        <Save className="w-4 h-4" />
                      </button>
                      <button title="Add to Vikunja" className="p-1.5 text-secondary hover:text-accent hover:bg-accent/10 rounded-lg transition-colors">
                        <ListTodo className="w-4 h-4" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

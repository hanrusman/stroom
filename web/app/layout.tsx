import type { Metadata } from "next";
import "./globals.css";
import { Inter } from "next/font/google";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Stroom | Your River of Insights",
  description: "Aggregated, AI-summarized insights from your favorite sources.",
  manifest: "/manifest.json",
  themeColor: "#0b0f19",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${inter.className} min-h-screen antialiased bg-background text-foreground flex flex-col md:flex-row`}>
        {/* Sidebar */}
        <aside className="md:w-64 glass shadow-xl md:h-screen sticky top-0 flex-shrink-0 flex flex-col p-6 z-10 hidden md:flex">
          <div className="flex items-center gap-3 mb-10">
            <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-primary to-accent opacity-90 blur-[2px] absolute"></div>
            <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-primary to-accent relative z-10 flex items-center justify-center shadow-lg">
              <div className="w-3 h-3 rounded-full bg-white animate-pulse"></div>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-white to-gray-400">
              Stroom.
            </h1>
          </div>
          
          <nav className="flex flex-col gap-2 flex-grow">
            {['Stream', 'Spiegel', 'Podcast'].map((item, idx) => (
              <a key={item} href={idx === 0 ? '/' : `/${item.toLowerCase()}`} className={`px-4 py-3 rounded-xl transition-all duration-300 font-medium ${idx === 0 ? 'bg-primary/20 text-primary border border-primary/20 shadow-[0_0_15px_rgba(59,130,246,0.15)]' : 'hover:bg-white/5 text-gray-400 hover:text-white'}`}>
                {item}
              </a>
            ))}
          </nav>
          
          <div className="text-xs text-secondary mt-auto">
            © 2026 Stroom
          </div>
        </aside>

        {/* Mobile Header */}
        <header className="md:hidden glass p-4 sticky top-0 z-20 flex justify-between items-center shadow-md border-b border-white/10">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-gradient-to-tr from-primary to-accent"></div>
            <h1 className="text-xl font-bold">Stroom.</h1>
          </div>
        </header>

        {/* Main Content */}
        <main className="flex-1 overflow-x-hidden p-6 md:p-10 relative">
          <div className="absolute top-[-100px] right-[-100px] w-[300px] h-[300px] bg-primary/20 rounded-full blur-[120px] pointer-events-none"></div>
          <div className="absolute bottom-[10%] left-[-100px] w-[250px] h-[250px] bg-accent/10 rounded-full blur-[100px] pointer-events-none"></div>
          {children}
        </main>
      </body>
    </html>
  );
}

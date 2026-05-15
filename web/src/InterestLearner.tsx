import React, { useState, useEffect } from 'react';
import { X, Plus, Lightbulb, Users, Tag } from 'lucide-react';
import { extractKeywords, createQualityScorerTopic, updateQualityScorerTopic } from './api';

interface InterestLearnerProps {
  itemId: string;
  title: string;
  summary?: string;
  onClose: () => void;
}

export const InterestLearner: React.FC<InterestLearnerProps> = ({ itemId, title, summary, onClose }) => {
  const [keywords, setKeywords] = useState<{term: string; score: number; type: string}[]>([]);
  const [persons, setPersons] = useState<string[]>([]);
  const [topics, setTopics] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedKeywords, setSelectedKeywords] = useState<string[]>([]);
  const [showNewTopic, setShowNewTopic] = useState(false);
  const [newTopicName, setNewTopicName] = useState('');
  const [newTopicKeywords, setNewTopicKeywords] = useState('');

  useEffect(() => {
    loadKeywords();
  }, []);

  const loadKeywords = async () => {
    try {
      const result = await extractKeywords(summary || title, title);
      // Remove duplicates from keywords
      const seen = new Set<string>();
      const unique = result.keywords.filter(k => {
        if (seen.has(k.term)) return false;
        seen.add(k.term);
        return true;
      });
      setKeywords(unique.slice(0, 10));
      setPersons(result.persons_mentioned);
      setTopics(result.topics_matched);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to extract keywords');
    } finally {
      setLoading(false);
    }
  };

  const toggleKeyword = (term: string) => {
    setSelectedKeywords(prev =>
      prev.includes(term) ? prev.filter(k => k !== term) : [...prev, term]
    );
  };

  const addToExistingTopic = async (topicName: string) => {
    try {
      // In a real implementation, we'd need to fetch current keywords first
      await updateQualityScorerTopic(topicName, selectedKeywords);
      setSelectedKeywords([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update topic');
    }
  };

  const createNewTopic = async () => {
    if (!newTopicName.trim()) return;
    try {
      // Gebruik handmatige keywords of selected keywords
      const keywords = newTopicKeywords.trim()
        ? newTopicKeywords.split(',').map(k => k.trim()).filter(Boolean)
        : selectedKeywords;
      await createQualityScorerTopic({
        name: newTopicName.trim(),
        keywords: keywords
      });
      setNewTopicName('');
      setNewTopicKeywords('');
      setShowNewTopic(false);
      setSelectedKeywords([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create topic');
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl max-w-lg w-full max-h-[80vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
        <div className="p-4 border-b border-brand-ink/10 flex items-center justify-between">
          <h3 className="font-semibold text-lg flex items-center gap-2 text-brand-ink">
            <Lightbulb size={20} className="text-amber-500" />
            Ontdekte interesses
          </h3>
          <button onClick={onClose} className="p-1 hover:bg-brand-surface rounded text-brand-ink/60">
            <X size={20} />
          </button>
        </div>

        <div className="p-4">
          {loading && (
            <div className="text-center py-8 text-brand-ink/50">
              Analyseren van content...
            </div>
          )}

          {error && (
            <div className="bg-red-50 text-red-600 p-3 rounded mb-4 text-sm border border-red-200">
              {error}
            </div>
          )}

          {!loading && (
            <>
              {/* Persons mentioned */}
              {persons.length > 0 && (
                <div className="mb-4">
                  <h4 className="text-sm font-medium text-brand-ink/70 mb-2 flex items-center gap-1">
                    <Users size={14} />
                    Personen die worden genoemd
                  </h4>
                  <div className="flex flex-wrap gap-1">
                    {persons.map(person => (
                      <span key={person} className="px-2 py-1 bg-brand-surface text-brand-ink rounded text-xs">
                        {person.replace('_', ' ')}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Topics matched */}
              {topics.length > 0 && (
                <div className="mb-4">
                  <h4 className="text-sm font-medium text-brand-ink/70 mb-2 flex items-center gap-1">
                    <Tag size={14} />
                    Passende onderwerpen
                  </h4>
                  <div className="flex flex-wrap gap-1">
                    {topics.map(topic => (
                      <span key={topic} className="px-2 py-1 bg-brand-accent/10 text-brand-accent rounded text-xs">
                        {topic}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Suggested keywords */}
              <div className="mb-4">
                <h4 className="text-sm font-medium text-brand-ink/70 mb-2">
                  Interessante termen
                </h4>
                <div className="flex flex-wrap gap-1">
                  {keywords.map(keyword => (
                    <button
                      key={keyword.term}
                      onClick={() => toggleKeyword(keyword.term)}
                      className={`px-2 py-1 rounded text-xs transition ${
                        selectedKeywords.includes(keyword.term)
                          ? 'bg-brand-accent text-white'
                          : 'bg-brand-surface text-brand-ink/70 hover:bg-brand-cream'
                      }`}
                    >
                      {keyword.term}
                      <span className="ml-1 opacity-60">({keyword.type})</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Actions for selected keywords */}
              {selectedKeywords.length > 0 && (
                <div className="border-t border-brand-ink/10 pt-4 mt-4">
                  <p className="text-sm text-brand-ink/60 mb-2">
                    {selectedKeywords.length} termen geselecteerd
                  </p>

                  {topics.length > 0 && (
                    <div className="mb-2">
                      <p className="text-xs text-brand-ink/50 mb-1">Toevoegen aan bestaand onderwerp:</p>
                      <div className="flex flex-wrap gap-1">
                        {topics.map(topic => (
                          <button
                            key={topic}
                            onClick={() => addToExistingTopic(topic)}
                            className="px-2 py-1 bg-brand-accent/10 text-brand-accent rounded text-xs hover:bg-brand-accent/20"
                          >
                            + {topic}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {!showNewTopic ? (
                    <button
                      onClick={() => setShowNewTopic(true)}
                      className="px-3 py-1.5 bg-brand-accent text-white rounded text-sm flex items-center gap-1"
                    >
                      <Plus size={14} />
                      Nieuw onderwerp maken
                    </button>
                  ) : (
                    <div className="space-y-2">
                      <input
                        type="text"
                        value={newTopicName}
                        onChange={(e) => setNewTopicName(e.target.value)}
                        placeholder="Naam van onderwerp (bijv. 'energy')"
                        className="w-full px-3 py-2 border border-brand-ink/20 rounded text-sm text-brand-ink placeholder:text-brand-ink/40"
                      />
                      <input
                        type="text"
                        value={newTopicKeywords}
                        onChange={(e) => setNewTopicKeywords(e.target.value)}
                        placeholder="Keywords, gescheiden door komma's (bijv. 'energie, kosten, belasting')"
                        className="w-full px-3 py-2 border border-brand-ink/20 rounded text-sm text-brand-ink placeholder:text-brand-ink/40"
                      />
                      <div className="flex gap-2">
                        <button
                          onClick={() => { setShowNewTopic(false); setNewTopicKeywords(''); }}
                          className="px-3 py-1.5 border border-brand-ink/20 rounded text-sm text-brand-ink hover:bg-brand-surface"
                        >
                          Annuleren
                        </button>
                        <button
                          onClick={() => createNewTopic()}
                          disabled={!newTopicName.trim() || !newTopicKeywords.trim()}
                          className="px-3 py-1.5 bg-brand-accent text-white rounded text-sm disabled:opacity-50"
                        >
                          Aanmaken
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        <div className="p-4 border-t border-brand-ink/10 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-brand-ink/60 hover:bg-brand-surface rounded transition"
          >
            Sluiten
          </button>
        </div>
      </div>
    </div>
  );
};

import React from 'react';
import { IconButton } from 'stroom-ds';
import { Bookmark, Archive, Play, X, Settings } from 'lucide-react';

export const Default = () => (
  <div className="flex items-center gap-2">
    <IconButton aria-label="Bewaren"><Bookmark size={18} /></IconButton>
    <IconButton aria-label="Archiveren"><Archive size={18} /></IconButton>
    <IconButton aria-label="Instellingen"><Settings size={18} /></IconButton>
  </div>
);

export const Filled = () => (
  <IconButton aria-label="Afspelen" filled><Play size={18} fill="currentColor" /></IconButton>
);

export const Sizes = () => (
  <div className="flex items-center gap-2">
    <IconButton aria-label="Klein" size="sm"><X size={16} /></IconButton>
    <IconButton aria-label="Middel" size="md"><X size={18} /></IconButton>
    <IconButton aria-label="Groot" size="lg"><X size={20} /></IconButton>
  </div>
);

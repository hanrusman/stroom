import React from 'react';
import { Input } from 'stroom-ds';
import { Search } from 'lucide-react';

export const Default = () => (
  <div className="w-80">
    <Input placeholder="Titel van de bron…" defaultValue="De Correspondent" />
  </div>
);

export const WithIcon = () => (
  <div className="w-80">
    <Input icon={<Search size={16} />} placeholder="Zoek in je stroom…" />
  </div>
);

export const Placeholder = () => (
  <div className="w-80">
    <Input placeholder="https://voorbeeld.nl/feed.xml" />
  </div>
);

export const Disabled = () => (
  <div className="w-80">
    <Input placeholder="Niet bewerkbaar" disabled />
  </div>
);

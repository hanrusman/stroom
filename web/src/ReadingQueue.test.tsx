// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { QueueButton, ReadingQueueProvider, useReadingQueue } from './ReadingQueue';
import { changeReadingQueue, fetchReadingQueueIds } from './api';
vi.mock('./api', () => ({changeReadingQueue: vi.fn(), fetchReadingQueueIds: vi.fn(), fetchReadingQueue: vi.fn(), setItemStatus: vi.fn()}));
let host: HTMLDivElement, root: Root;
function Harness() { const q=useReadingQueue(); return <><QueueButton id="one" /><QueueButton id="archived" archived /><span role="status">{Array.from(q.ids).join(',')}</span><span role="alert">{q.error}</span></>; }
beforeEach(async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  vi.mocked(fetchReadingQueueIds).mockResolvedValue([]); vi.mocked(changeReadingQueue).mockImplementation(async (id, queued) => { vi.mocked(fetchReadingQueueIds).mockResolvedValue(queued ? [id] : []); });
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  await act(async () => root.render(<ReadingQueueProvider><Harness /></ReadingQueueProvider>));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.resetAllMocks(); });
it('adds then removes after server confirmation; archived is disabled',async () => {
  const button=host.querySelector('button')!;
  await act(async () => button.click());
  expect(changeReadingQueue).toHaveBeenLastCalledWith('one',true);
  expect(button.getAttribute('aria-pressed')).toBe('true');
  await act(async () => button.click());
  expect(changeReadingQueue).toHaveBeenLastCalledWith('one',false);
  expect(button.getAttribute('aria-pressed')).toBe('false');
  expect(host.querySelectorAll('button')[1].disabled).toBe(true);
});
it('does not claim success on failed server write',async () => {
  vi.mocked(changeReadingQueue).mockRejectedValue(new Error('offline'));
  await act(async () => host.querySelector('button')!.click());
  expect(host.querySelector('[role=status]')!.textContent).toBe('');
  expect(host.querySelector('[role=alert]')!.textContent).toContain('offline');
});
it('archive immediately clears membership',async () => {
  await act(async () => host.querySelector('button')!.click());
  await act(async () => window.dispatchEvent(new CustomEvent('stroom:item-status',{detail:{id:'one',status:'archived'}})));
  expect(host.querySelector('[role=status]')!.textContent).toBe('');
});

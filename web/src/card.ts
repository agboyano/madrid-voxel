import type { Facts } from './types';
import { el } from './util';

// The info card of a selected landmark: its names, kind and the facts Wikidata gives for it (scripts/fetch_wikidata.py,
// static data written at build time; the viewer asks Wikidata nothing), with links to its website and Wikipedia.
const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

export class Card {
  private readonly el = el('div', '');

  constructor() {
    this.el.id = 'card';
    this.el.hidden = true;
    this.el.addEventListener('click', (e) => { if ((e.target as HTMLElement).closest('.close')) this.hide(); });
    addEventListener('keydown', (e) => { if (e.key === 'Escape') this.hide(); });
  }

  show(f: Facts) {
    const rows: [string, string | number | undefined][] = [
      ['Built', f.year], ['Architect', f.by], ['Height', f.height && `${f.height} m`], ['Style', f.style],
      ['Heritage', f.heritage], ['Rebuilt', f.rebuilt]];
    const facts = rows.filter(([, v]) => v).map(([k, v]) => `<dt>${k}</dt><dd>${esc(String(v))}</dd>`).join('');
    const links = [f.site && `<a href="${esc(f.site)}" target="_blank" rel="noopener">Website</a>`,
      f.wiki && `<a href="${esc(f.wiki)}" target="_blank" rel="noopener">Wikipedia</a>`].filter(Boolean).join('');
    this.el.innerHTML = `<button class="close" aria-label="Close">×</button><b>${esc(f.name)}</b>`
      + (f.en ? `<i>${esc(f.en)}</i>` : '') + `<span>${esc(f.kind)}</span>`
      + (facts ? `<dl>${facts}</dl>` : '') + (links ? `<p>${links}</p>` : '');
    this.el.hidden = false;
  }

  hide() { this.el.hidden = true; }
}

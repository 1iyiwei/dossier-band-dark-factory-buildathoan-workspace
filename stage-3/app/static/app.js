/* Dossier browser UI: plain JavaScript no build step, no external resources.
   Every screen is the same page shell; this file draws the screen for location.pathname. */
'use strict';

const FIELDS = [
  ['legal_name', 'Legal name'],
  ['hq_city', 'Headquarters'],
  ['ceo', 'Chief executive'],
  ['founded_year', 'Founded'],
  ['headcount_range', 'Headcount'],
  ['funding_total', 'Total funding'],
];
const FIELD_LABEL = Object.fromEntries(FIELDS);
const PROVIDER_LABEL = { nimble: 'Nimble', tavily: 'Tavily', kernel: 'Kernel', browserbase: 'Browserbase' };
const KIND_LABEL = { own: 'Company site', filing: 'Filing', news: 'News', aggregator: 'Aggregator' };
const STATUS_LABEL = { known: 'Known', unknown: 'Unknown', contested: 'Contested' };
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const POLL_MS = 1000;
const SESSION_KEY = 'dossier.session';

// ------------------------------------------------------------------ small helpers

function el(tag, props = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'testid') node.setAttribute('data-testid', value);
    else if (key === 'data') for (const [name, v] of Object.entries(value)) node.setAttribute('data-' + name, v);
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid !== null && kid !== undefined && kid !== false) node.append(kid);
  }
  return node;
}

function mount(...nodes) {
  const main = document.getElementById('main');
  main.replaceChildren(...nodes.flat());
}

function go(path) { window.location.assign(path); }

function newKey() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (window.crypto && crypto.getRandomValues) crypto.getRandomValues(bytes);
  else for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/** §4: whitespace removed, lowercased, one trailing `.` and one leading `www.` removed. */
function normaliseDomain(raw) {
  let d = String(raw).trim().toLowerCase();
  if (d.endsWith('.')) d = d.slice(0, -1);
  if (d.startsWith('www.')) d = d.slice(4);
  return d;
}

// ------------------------------------------------------------------ formatting for people

function groupDigits(n) {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function formatValue(field, value) {
  if (value === null || value === undefined) return '';
  if (field === 'funding_total') return '$' + groupDigits(value);
  if (field === 'founded_year') return String(value);
  if (field === 'headcount_range') {
    const text = String(value).replace(/\d+/g, (d) => groupDigits(d));
    return text + ' employees';
  }
  return String(value);
}

function dataValue(value) { return value === null || value === undefined ? '' : String(value); }

/** "2026-03-01T09:00:00+00:00" as "1 Mar 2026, 09:00 UTC", in the offset it was written with. */
function formatTime(stamp, { dateOnlyAtMidnight = false } = {}) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?([Zz]|[+-]\d{2}:\d{2})$/.exec(stamp || '');
  if (!m) return stamp || '';
  const date = `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
  if (dateOnlyAtMidnight && m[4] === '00' && m[5] === '00' && (m[6] || '00') === '00') return date;
  const zone = /^[Zz]$/.test(m[7]) || m[7] === '+00:00' || m[7] === '-00:00' ? 'UTC' : 'UTC' + m[7];
  return `${date}, ${m[4]}:${m[5]} ${zone}`;
}

function plural(n, word) { return `${n} ${word}${n === 1 ? '' : 's'}`; }

function hostOf(url) {
  try {
    const u = new URL(url);
    return u.hostname + (u.pathname && u.pathname !== '/' ? u.pathname : '');
  } catch (e) { return url; }
}

// ------------------------------------------------------------------ session and API

function session() {
  try { return JSON.parse(localStorage.getItem(SESSION_KEY) || 'null'); } catch (e) { return null; }
}
function saveSession(reply) {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ token: reply.token, user_id: reply.user_id, display_name: reply.display_name }));
}
function endSession() { localStorage.removeItem(SESSION_KEY); }

class NetworkError extends Error {}   // no usable answer arrived: the outcome of a write is unknown
class AuthError extends Error {}      // the saved token was refused

/** One API call. Resolves {status, data} for any HTTP answer; rejects with NetworkError or AuthError. */
async function api(method, path, { body, key, timeoutMs = 12000 } = {}) {
  const headers = { Accept: 'application/json' };
  const saved = session();
  if (saved && saved.token) headers.Authorization = 'Bearer ' + saved.token;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (key) headers['Idempotency-Key'] = key;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let status, data = null;
  try {
    const response = await fetch(path, {
      method, headers, signal: controller.signal, cache: 'no-store',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    status = response.status;
    const text = await response.text();
    if (text) { try { data = JSON.parse(text); } catch (e) { data = null; } }
  } catch (e) {
    throw new NetworkError(String(e));
  } finally {
    clearTimeout(timer);
  }
  if (status === 401 && !path.startsWith('/auth/')) {
    endSession();
    go('/login?next=' + encodeURIComponent(location.pathname));
    throw new AuthError('signed out');
  }
  return { status, data };
}

function errorMessage(result, fallback) {
  const message = result && result.data && result.data.error && result.data.error.message;
  return message ? message.charAt(0).toUpperCase() + message.slice(1) + (/[.!?]$/.test(message) ? '' : '.') : fallback;
}

// ------------------------------------------------------------------ shell

function drawTopbar() {
  const saved = session();
  const path = location.pathname;
  const link = (href, text, active) => el('a', { href, text, 'aria-current': active ? 'page' : null });
  const account = saved
    ? el('div', { class: 'account' },
        el('span', { class: 'who', testid: 'current-user' }, 'Signed in as ', el('strong', { text: saved.display_name })),
        el('button', { class: 'btn btn-small', type: 'button', testid: 'logout-button', text: 'Log out',
          onclick: () => { endSession(); go('/login'); } }))
    : el('div', { class: 'account' },
        el('a', { class: 'btn btn-small', href: '/login', text: 'Log in' }),
        el('a', { class: 'btn btn-small btn-primary', href: '/signup', text: 'Sign up' }));
  document.getElementById('topbar').replaceChildren(el('div', { class: 'topbar-inner' },
    el('a', { class: 'brand', href: '/', 'aria-label': 'Dossier home' },
      brandMark(),
      'Dossier'),
    saved ? el('nav', { class: 'nav', 'aria-label': 'Main' },
      link('/', 'Dossiers', path === '/' || (path.startsWith('/dossiers/') && !path.endsWith('/evidence'))),
      link('/contested', 'Contested', path === '/contested')) : el('span', { class: 'nav' }),
    account));
}

function brandMark() {
  const mark = el('span', { class: 'brand-mark', 'aria-hidden': 'true' });
  mark.innerHTML = '<svg width="16" height="16" viewBox="0 0 32 32" fill="none" stroke="#fff" stroke-width="3" '
    + 'stroke-linejoin="round" stroke-linecap="round"><path d="M9 6h10l5 5v15H9z"/><path d="M13 17h7M13 22h5"/></svg>';
  return mark;
}

function requireSession() {
  if (session()) return true;
  go('/login?next=' + encodeURIComponent(location.pathname));
  return false;
}

function badge(kind, text, extra = {}) {
  return el('span', { class: `badge badge-${kind}`, text, ...extra });
}

function spinner() { return el('span', { class: 'spinner', 'aria-hidden': 'true' }); }

function loadingBlock(label) {
  return el('div', { class: 'stack-sm', role: 'status', 'aria-live': 'polite' },
    el('p', { class: 'muted' }, spinner(), ' ', label),
    el('div', { class: 'skeleton' }), el('div', { class: 'skeleton' }));
}

function errorBlock(message, retry) {
  return el('div', { class: 'notice notice-error', role: 'alert' },
    el('strong', { text: 'Something went wrong' }), message,
    retry ? el('div', { class: 'row' }, el('button', { class: 'btn btn-small', type: 'button', text: 'Try again', onclick: retry })) : null);
}

// ------------------------------------------------------------------ signup and login

function authScreen(mode) {
  const saved = session();
  const next = (() => {
    const wanted = new URLSearchParams(location.search).get('next');
    return wanted && wanted.startsWith('/') && !wanted.startsWith('//') ? wanted : '/';
  })();
  const signup = mode === 'signup';
  document.title = (signup ? 'Sign up' : 'Log in') + ' · Dossier';
  const errorSlot = el('div');
  const submit = el('button', { class: 'btn btn-primary', type: 'submit', testid: signup ? 'signup-submit' : 'login-submit', text: signup ? 'Create account' : 'Log in' });
  const input = (id, label, type, testid, extra = {}) => el('div', { class: 'field' },
    el('label', { for: id, text: label }),
    el('input', { id, name: id, type, testid, required: true, ...extra }));
  const fields = signup
    ? [input('display_name', 'Display name', 'text', 'signup-display-name', { autocomplete: 'name', maxlength: 100 }),
       input('email', 'Email', 'email', 'signup-email', { autocomplete: 'email' }),
       input('password', 'Password', 'password', 'signup-password', { autocomplete: 'new-password' })]
    : [input('email', 'Email', 'email', 'login-email', { autocomplete: 'email' }),
       input('password', 'Password', 'password', 'login-password', { autocomplete: 'current-password' })];
  const form = el('form', { class: 'card card-narrow stack-sm', novalidate: true },
    el('h1', { text: signup ? 'Create your account' : 'Welcome back' }),
    el('p', { class: 'lede', text: signup ? 'Researchers share one set of dossiers.' : 'Log in to read and research company dossiers.' }),
    saved ? el('p', { class: 'notice notice-info', text: `You are signed in as ${saved.display_name}. Submitting signs you in as someone else.` }) : null,
    errorSlot, fields,
    signup ? el('p', { class: 'hint', text: 'Passwords need at least 8 characters.' }) : null,
    el('div', { class: 'row' }, submit,
      signup ? el('a', { href: '/login', text: 'I already have an account' }) : el('a', { href: '/signup', text: 'Create an account' })));
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const value = (name) => form.elements[name].value;
    errorSlot.replaceChildren();
    submit.disabled = true;
    submit.replaceChildren(spinner(), signup ? ' Creating account…' : ' Logging in…');
    const restore = () => { submit.disabled = false; submit.textContent = signup ? 'Create account' : 'Log in'; };
    try {
      const body = signup
        ? { email: value('email').trim(), password: value('password'), display_name: value('display_name').trim() }
        : { email: value('email').trim(), password: value('password') };
      const result = await api('POST', signup ? '/auth/signup' : '/auth/login', { body });
      if (result.status === 200 || result.status === 201) {
        saveSession(result.data);
        go(next);
        return;
      }
      const friendly = { 401: 'That email and password do not match an account.', 409: 'An account with that email already exists. Try logging in.' };
      errorSlot.replaceChildren(el('p', { class: 'notice notice-error', role: 'alert', testid: 'auth-error', text: friendly[result.status] || errorMessage(result, 'Could not complete that request.') }));
    } catch (e) {
      errorSlot.replaceChildren(el('p', { class: 'notice notice-error', role: 'alert', testid: 'auth-error', text: 'The server did not answer. Check your connection and try again.' }));
    }
    restore();
  });
  mount(form);
}

// ------------------------------------------------------------------ dossier list

async function readAllDossiers(q) {
  const rows = [];
  for (let offset = 0; ; offset += 200) {
    const params = new URLSearchParams({ limit: '200', offset: String(offset) });
    if (q) params.set('q', q);
    const result = await api('GET', '/dossiers?' + params);
    if (result.status !== 200) throw new NetworkError(errorMessage(result, 'The list could not be read.'));
    rows.push(...result.data.dossiers);
    if (!result.data.has_more) return rows;
  }
}

function homeScreen() {
  document.title = 'Dossiers · Dossier';
  const messages = el('div', { class: 'stack-sm', 'aria-live': 'polite' });
  const domainInput = el('input', { id: 'research-domain', type: 'text', testid: 'research-domain', placeholder: 'acme-robotics.test',
    autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', 'aria-describedby': 'research-hint' });
  const submit = el('button', { class: 'btn btn-primary', type: 'submit', testid: 'research-submit', text: 'Research' });
  const form = el('form', { class: 'card research-form', novalidate: true },
    el('div', { class: 'row' },
      el('div', { class: 'grow' }, el('label', { for: 'research-domain', text: 'Company domain' }), domainInput), submit),
    el('p', { class: 'hint', id: 'research-hint', text: 'A web domain such as acme-robotics.test. Research runs in the background and takes a few seconds.' }),
    messages);

  // One request key per attempt: a retry of an unanswered request sends the same key and body.
  let pending = null;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const text = domainInput.value;
    if (!pending || pending.text !== text) pending = { text, key: newKey() };
    messages.replaceChildren();
    submit.disabled = true;
    submit.replaceChildren(spinner(), ' Researching…');
    const finish = () => { submit.disabled = false; submit.textContent = 'Research'; };
    let result;
    try {
      result = await api('POST', '/dossiers', { body: { domain: text }, key: pending.key });
    } catch (e) {
      if (e instanceof AuthError) return;
      messages.replaceChildren(el('div', { class: 'notice notice-uncertain', role: 'status', testid: 'research-uncertain' },
        el('strong', { text: 'We did not hear back' }),
        'The request may or may not have reached the server. Press Research again to retry: the same request is sent, so at most one build starts.'));
      finish();
      return;
    }
    if (result.status === 200 || result.status === 202) {
      pending = null;
      go('/dossiers/' + encodeURIComponent(result.data.domain));
      return;
    }
    if (result.status >= 500) {
      messages.replaceChildren(el('div', { class: 'notice notice-uncertain', role: 'status', testid: 'research-uncertain' },
        el('strong', { text: 'The server could not confirm the request' }),
        'It may or may not have been accepted. Press Research again to retry safely with the same request.'));
    } else {
      pending = null;
      messages.replaceChildren(el('div', { class: 'notice notice-error', role: 'alert', testid: 'research-error' },
        el('strong', { text: 'That domain was not accepted' }),
        errorMessage(result, 'The request was refused.')));
    }
    finish();
  });

  const search = el('input', { id: 'dossier-search', type: 'search', testid: 'dossier-search', placeholder: 'Search by domain or company name', autocomplete: 'off' });
  const listArea = el('div', { 'aria-live': 'polite' });
  let seq = 0, applied = 0, debounce = null;

  async function load() {
    const mine = ++seq;
    if (!listArea.firstChild) listArea.replaceChildren(loadingBlock('Loading dossiers…'));
    let node;
    try {
      const rows = await readAllDossiers(search.value);
      node = rows.length ? el('div', { class: 'dossier-list', testid: 'dossier-list' }, rows.map(dossierItem))
        : el('div', { class: 'empty', testid: 'empty-dossiers' },
            el('h2', { text: search.value.trim() ? 'No dossiers match' : 'No dossiers yet' }),
            el('p', { text: search.value.trim() ? 'Try a different search, or research this company above.' : 'Research a company domain above to create the first one.' }));
    } catch (e) {
      if (e instanceof AuthError) return;
      node = errorBlock('The dossier list could not be read.', load);
    }
    if (mine < applied) return;          // latest read wins
    applied = mine;
    listArea.replaceChildren(node);
  }
  search.addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(load, 150); });

  mount(el('div', { class: 'stack' },
    el('div', { class: 'hero' }, el('h1', { text: 'Company dossiers' }),
      el('p', { class: 'lede', text: 'Six facts per company, each with the sources it came from. Where sources disagree, the strongest one is shown and the dispute is flagged.' })),
    form,
    el('section', { class: 'stack-sm', 'aria-labelledby': 'list-title' },
      el('div', { class: 'row-between' }, el('h2', { id: 'list-title', text: 'Researched companies' }),
        el('button', { class: 'btn btn-quiet btn-small', type: 'button', text: 'Reload list', onclick: load })),
      el('div', {}, el('label', { for: 'dossier-search', text: 'Filter dossiers' }), search),
      listArea)));
  return load();
}

function dossierItem(row) {
  return el('a', { class: 'dossier-item', href: '/dossiers/' + encodeURIComponent(row.domain), testid: 'dossier-item-' + row.domain, data: { state: row.state } },
    el('div', {}, el('div', { class: 'domain', text: row.domain }),
      row.legal_name ? el('div', { class: 'legal', text: row.legal_name }) : null),
    badge(row.state, row.state),
    el('div', { class: 'meta', text: [
      row.researched_at ? 'Researched ' + formatTime(row.researched_at) : 'Not researched yet',
      plural(row.spent_units, 'unit') + ' spent'].join(' · ') }));
}

// ------------------------------------------------------------------ one dossier

/** Loads a dossier and keeps the latest answer. Reads are numbered when issued; an answer to an earlier read never replaces a later one. */
class DossierReader {
  constructor(domain, onChange) {
    this.domain = domain;
    this.onChange = onChange;
    this.seq = 0; this.applied = 0; this.inFlight = 0; this.timer = null;
    this.view = { kind: 'loading' };
  }

  async read() {
    const mine = ++this.seq;
    this.inFlight++;
    let next;
    try {
      const result = await api('GET', '/dossiers/' + encodeURIComponent(this.domain));
      if (result.status === 200) next = { kind: 'ready', dossier: result.data };
      else if (result.status === 404 || result.status === 422) next = { kind: 'notfound', status: result.status };
      else next = { kind: 'error', message: errorMessage(result, 'The dossier could not be read.') };
    } catch (e) {
      if (e instanceof AuthError) return;
      next = { kind: 'error', message: 'The server did not answer.' };
    } finally {
      this.inFlight--;
    }
    if (mine < this.applied) return;     // a later read has already been shown
    this.applied = mine;
    if (next.kind === 'error' && this.view.kind === 'ready') next = { ...this.view, stale: next.message };
    this.view = next;
    this.onChange(next);
    this.poll();
  }

  /** While the dossier is building, read it again every second until it is ready or failed. */
  poll() {
    const building = this.view.kind === 'ready' && this.view.dossier.state === 'building';
    if (building && !this.timer) {
      this.timer = setInterval(() => { if (this.inFlight < 3) this.read(); }, POLL_MS);
    } else if (!building && this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}

function candidateFor(field, citation) {
  return (field.candidates || []).find((c) => c.url === citation.url && c.provider === citation.provider && c.excerpt === citation.excerpt);
}

function sourceLine(url, provider, kind, publishedAt) {
  return el('div', { class: 'source' },
    el('a', { href: url, target: '_blank', rel: 'noopener noreferrer', text: hostOf(url) }),
    badge('provider', PROVIDER_LABEL[provider] || provider),
    kind ? badge('kind', KIND_LABEL[kind] || kind) : null,
    el('span', { text: publishedAt ? 'Published ' + formatTime(publishedAt, { dateOnlyAtMidnight: true }) : 'Publication time unknown' }));
}

function fieldCard(domain, [name, label], field) {
  const status = field.status;
  const citations = field.citations || [];
  const distinct = new Set((field.candidates || []).map((c) => JSON.stringify(c.value))).size;
  return el('article', { class: 'card fcard', testid: 'field-' + name, data: { status } },
    el('div', { class: 'fcard-head' }, el('h2', { class: 'fcard-label', text: label }), badge(status, STATUS_LABEL[status] || status)),
    field.value !== null && field.value !== undefined
      ? el('p', { class: 'value', testid: 'field-value-' + name, data: { value: dataValue(field.value) }, text: formatValue(name, field.value) })
      : el('p', { class: 'value value-unknown', testid: 'field-unknown-' + name, text: 'No source states this' }),
    status === 'contested'
      ? el('p', { class: 'contested-note', testid: 'field-contested-' + name },
          el('strong', { text: 'Sources disagree. ' }), `${distinct} different values found; showing the one from the strongest, most recent source. `,
          el('a', { href: `/dossiers/${encodeURIComponent(domain)}/evidence`, text: 'Compare candidates' }))
      : null,
    el('div', { class: 'citations', testid: 'field-citations-' + name },
      citations.map((citation, index) => {
        const candidate = candidateFor(field, citation);
        return el('figure', { class: 'citation', testid: `citation-${name}-${index + 1}`, data: { provider: citation.provider } },
          el('blockquote', { class: 'quote', text: citation.excerpt }),
          sourceLine(citation.url, citation.provider, candidate && candidate.kind, candidate && candidate.published_at));
      })));
}

function dossierBanner(dossier) {
  if (dossier.state === 'building') {
    return el('div', { class: 'notice notice-info', role: 'status' }, el('strong', {}, spinner(), ' Research in progress'),
      'This page checks for results every second and will update by itself.');
  }
  if (dossier.state === 'failed') {
    return el('div', { class: 'notice notice-error', role: 'status' }, el('strong', { text: 'The last research run failed' }),
      dossier.researched_at ? 'The fields below are from the last successful run. Refresh to try again.' : 'Nothing was found yet. Refresh to try again.');
  }
  return null;
}

function dossierScreen(rawDomain) {
  const domain = normaliseDomain(rawDomain);
  document.title = domain + ' · Dossier';
  const head = el('div', { class: 'dossier-head' });
  const body = el('div', { 'aria-live': 'polite' });
  const messages = el('div', { class: 'stack-sm', 'aria-live': 'polite' });
  const refreshButton = el('button', { class: 'btn btn-primary', type: 'button', testid: 'dossier-refresh', text: 'Refresh research' });
  const reloadButton = el('button', { class: 'btn', type: 'button', testid: 'dossier-reload', text: 'Reload' });
  const evidenceLink = el('a', { class: 'btn', href: `/dossiers/${encodeURIComponent(domain)}/evidence`, testid: 'dossier-evidence-link', text: 'View all evidence' });
  const actions = el('div', { class: 'actions' }, refreshButton, reloadButton, evidenceLink);
  const staleNote = el('div');

  const reader = new DossierReader(domain, draw);

  function draw(view) {
    refreshButton.disabled = refreshing;
    refreshButton.hidden = view.kind === 'notfound';
    evidenceLink.hidden = view.kind === 'notfound';
    staleNote.replaceChildren(view.stale ? el('p', { class: 'notice notice-uncertain', role: 'status', text: 'The latest read failed, so the data shown may be out of date. ' + view.stale }) : '');
    if (view.kind === 'loading') {
      head.replaceChildren(el('div', { class: 'dossier-title' }, el('h1', { testid: 'dossier-domain', text: domain })));
      body.replaceChildren(loadingBlock('Loading dossier…'));
      return;
    }
    if (view.kind === 'notfound') {
      head.replaceChildren(el('div', { class: 'dossier-title' }, el('h1', { testid: 'dossier-domain', text: domain })));
      body.replaceChildren(el('div', { class: 'empty', testid: 'dossier-not-found' },
        el('h2', { text: view.status === 422 ? 'That is not a valid domain' : 'No dossier for this domain yet' }),
        el('p', { text: view.status === 422 ? 'Check the spelling, or go back to the list.' : 'Research it from the dossier list, or reload if another researcher just started it.' }),
        el('p', {}, el('a', { class: 'btn btn-primary', href: '/', text: 'Back to dossiers' }))));
      return;
    }
    if (view.kind === 'error') {
      head.replaceChildren(el('div', { class: 'dossier-title' }, el('h1', { testid: 'dossier-domain', text: domain })));
      body.replaceChildren(errorBlock(view.message, () => reader.read()));
      return;
    }
    const d = view.dossier;
    head.replaceChildren(
      el('div', { class: 'dossier-title' }, el('h1', { testid: 'dossier-domain', text: d.domain }),
        badge(d.state, d.state, { 'data-testid': 'dossier-state' })),
      el('dl', { class: 'facts' },
        d.researched_at ? el('div', {}, el('dt', { text: 'Researched' }),
          el('dd', { testid: 'dossier-researched-at' }, formatTime(d.researched_at), ' ', el('span', { class: 'mono small', text: '(' + d.researched_at + ')' }))) : null,
        el('div', {}, el('dt', { text: 'Spent' }),
          el('dd', { testid: 'dossier-spent', data: { units: d.spent_units }, text: plural(d.spent_units, 'unit') }))));
    body.replaceChildren(el('div', { class: 'stack' }, dossierBanner(d) || '',
      el('div', { class: 'fields' }, FIELDS.map((f) => fieldCard(d.domain, f, d.fields[f[0]])))));
  }

  // Refresh: one request key per attempt, reused when the answer was lost.
  let refreshing = false, refreshKey = null;
  refreshButton.addEventListener('click', async () => {
    if (!refreshKey) refreshKey = newKey();
    refreshing = true;
    messages.replaceChildren();
    refreshButton.disabled = true;
    refreshButton.replaceChildren(spinner(), ' Refreshing…');
    const done = () => { refreshing = false; refreshButton.disabled = false; refreshButton.textContent = 'Refresh research'; };
    let result;
    try {
      result = await api('POST', `/dossiers/${encodeURIComponent(domain)}/refresh`, { key: refreshKey });
    } catch (e) {
      done();
      if (e instanceof AuthError) return;
      messages.replaceChildren(el('div', { class: 'notice notice-uncertain', role: 'status', testid: 'refresh-uncertain' },
        el('strong', { text: 'We did not hear back' }),
        'The refresh may or may not have started. Press Refresh again to retry: the same request is sent, so at most one build starts.'));
      return;
    }
    done();
    if (result.status === 200 || result.status === 202) {
      refreshKey = null;
      await reader.read();
      return;
    }
    if (result.status >= 500) {
      messages.replaceChildren(el('div', { class: 'notice notice-uncertain', role: 'status', testid: 'refresh-uncertain' },
        el('strong', { text: 'The server could not confirm the refresh' }),
        'It may or may not have started. Press Refresh again to retry safely with the same request.'));
      return;
    }
    refreshKey = null;
    messages.replaceChildren(el('div', { class: 'notice notice-error', role: 'alert', testid: 'refresh-error' },
      el('strong', { text: 'The refresh was refused' }), errorMessage(result, 'Try again in a moment.')));
  });
  reloadButton.addEventListener('click', () => reader.read());

  mount(el('div', { class: 'stack' },
    el('p', { class: 'crumbs' }, el('a', { href: '/', text: 'Dossiers' }), ' / ', domain),
    head, actions, messages, staleNote, body));
  draw(reader.view);
  return reader.read();
}

// ------------------------------------------------------------------ evidence

function candidateCard(name, candidate, index) {
  return el('article', { class: 'card candidate', testid: `candidate-${name}-${index + 1}`, data: {
    value: dataValue(candidate.value), provider: candidate.provider, kind: candidate.kind || '', url: candidate.url,
    'published-at': candidate.published_at || '', selected: candidate.selected ? 'true' : 'false' } },
    el('div', { class: 'cand-head' },
      el('span', { class: 'cvalue', text: formatValue(name, candidate.value) }),
      candidate.selected ? badge('selected', 'Selected') : null),
    el('blockquote', { class: 'quote', text: candidate.excerpt }),
    sourceLine(candidate.url, candidate.provider, candidate.kind || 'aggregator', candidate.published_at),
    el('p', { class: 'small muted', text: (candidate.kind ? '' : 'Imported from an earlier version; page kind unknown, ranked as an aggregator. ') + 'Retrieved ' + formatTime(candidate.retrieved_at) }));
}

function evidenceScreen(rawDomain) {
  const domain = normaliseDomain(rawDomain);
  document.title = 'Evidence for ' + domain + ' · Dossier';
  const body = el('div', { 'aria-live': 'polite' });
  const reader = new DossierReader(domain, draw);
  function draw(view) {
    if (view.kind === 'loading') { body.replaceChildren(loadingBlock('Loading evidence…')); return; }
    if (view.kind === 'notfound') {
      body.replaceChildren(el('div', { class: 'empty', testid: 'dossier-not-found' },
        el('h2', { text: 'No dossier for this domain yet' }),
        el('p', {}, el('a', { class: 'btn btn-primary', href: '/', text: 'Back to dossiers' }))));
      return;
    }
    if (view.kind === 'error') { body.replaceChildren(errorBlock(view.message, () => reader.read())); return; }
    const d = view.dossier;
    body.replaceChildren(el('div', { class: 'stack' },
      d.state === 'building' ? el('div', { class: 'notice notice-info', role: 'status' }, el('strong', {}, spinner(), ' Research in progress'),
        'These candidates are from the last completed run. Reload to see the new ones.') : null,
      FIELDS.map(([name, label]) => {
        const field = d.fields[name];
        const candidates = field.candidates || [];
        return el('section', { class: 'section', 'aria-labelledby': 'h-' + name },
          el('h2', { id: 'h-' + name }, label, ' ', badge(field.status, STATUS_LABEL[field.status] || field.status),
            el('span', { class: 'small muted', text: plural(candidates.length, 'candidate') })),
          el('div', { class: 'candidates', testid: 'evidence-' + name },
            candidates.length ? candidates.map((c, i) => candidateCard(name, c, i))
              : el('div', { class: 'empty', testid: 'evidence-empty-' + name }, el('p', { text: 'No source states this field.' }))));
      })));
  }
  mount(el('div', { class: 'stack' },
    el('p', { class: 'crumbs' }, el('a', { href: '/', text: 'Dossiers' }), ' / ',
      el('a', { href: '/dossiers/' + encodeURIComponent(domain), text: domain }), ' / Evidence'),
    el('div', { class: 'row-between' },
      el('div', { class: 'stack-sm' }, el('h1', { text: 'Evidence' }),
        el('p', { class: 'lede', text: 'Every value a source states, strongest first. The selected one is shown on the dossier: company and filing sources outrank news, news outranks aggregators, and newer outranks older.' })),
      el('button', { class: 'btn', type: 'button', testid: 'evidence-reload', text: 'Reload', onclick: () => reader.read() })),
    body));
  draw(reader.view);
  return reader.read();
}

// ------------------------------------------------------------------ contested fields

async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) { const i = next++; results[i] = await fn(items[i]); }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}

function contestedScreen() {
  document.title = 'Contested fields · Dossier';
  const body = el('div', { 'aria-live': 'polite' });
  let seq = 0, applied = 0;
  async function load() {
    const mine = ++seq;
    if (!body.firstChild) body.replaceChildren(loadingBlock('Looking for disputed fields…'));
    let node;
    try {
      const rows = await readAllDossiers('');
      const dossiers = await mapLimit(rows, 6, async (row) => {
        const result = await api('GET', '/dossiers/' + encodeURIComponent(row.domain));
        if (result.status === 404) return null;
        if (result.status !== 200) throw new NetworkError('read failed');
        return result.data;
      });
      const items = [];
      for (const dossier of dossiers.filter(Boolean).sort((a, b) => (a.domain < b.domain ? -1 : a.domain > b.domain ? 1 : 0))) {
        for (const [name] of FIELDS) {
          const field = dossier.fields[name];
          if (field.status === 'contested') items.push(contestedItem(dossier.domain, name, field));
        }
      }
      node = items.length ? el('div', { class: 'contested-list', testid: 'contested-list' }, items)
        : el('div', { class: 'empty', testid: 'empty-contested' }, el('h2', { text: 'Nothing is contested' }),
            el('p', { text: 'Every field with a source has sources that agree.' }));
    } catch (e) {
      if (e instanceof AuthError) return;
      node = errorBlock('The dossiers could not be read.', load);
    }
    if (mine < applied) return;
    applied = mine;
    body.replaceChildren(node);
  }
  mount(el('div', { class: 'stack' },
    el('div', { class: 'row-between' },
      el('div', { class: 'stack-sm' }, el('h1', { text: 'Contested fields' }),
        el('p', { class: 'lede', text: 'Fields where sources give different values. Each one links to its evidence.' })),
      el('button', { class: 'btn', type: 'button', text: 'Reload', onclick: load })),
    body));
  return load();
}

function contestedItem(domain, name, field) {
  const seen = new Map();
  for (const c of field.candidates) { const k = JSON.stringify(c.value); if (!seen.has(k)) seen.set(k, c.value); }
  return el('a', { class: 'contested-item', href: `/dossiers/${encodeURIComponent(domain)}/evidence`, testid: `contested-item-${domain}-${name}`,
    data: { value: dataValue(field.value) } },
    el('div', { class: 'cand-head' }, el('strong', { text: domain }), ' ', el('span', { text: FIELD_LABEL[name] }),
      el('span', { class: 'mono small', text: name }), badge('contested', 'Contested')),
    el('ul', { class: 'values', 'aria-label': 'Candidate values' },
      Array.from(seen.values(), (value) => el('li', { data: { selected: JSON.stringify(value) === JSON.stringify(field.value) ? 'true' : 'false' },
        text: formatValue(name, value) + (JSON.stringify(value) === JSON.stringify(field.value) ? ' (shown)' : '') }))));
}

// ------------------------------------------------------------------ routing

function route() {
  drawTopbar();
  let path = location.pathname;
  try { path = decodeURIComponent(path); } catch (e) { /* keep the raw path */ }
  if (path === '/signup') return authScreen('signup');
  if (path === '/login') return authScreen('login');
  if (!requireSession()) return null;
  if (path === '/') return homeScreen();
  if (path === '/contested') return contestedScreen();
  let match = /^\/dossiers\/([^/]+)\/evidence\/?$/.exec(path);
  if (match) return evidenceScreen(match[1]);
  match = /^\/dossiers\/([^/]+)\/?$/.exec(path);
  if (match) return dossierScreen(match[1]);
  mount(el('div', { class: 'empty' }, el('h1', { text: 'Page not found' }), el('p', {}, el('a', { href: '/', text: 'Back to dossiers' }))));
  return null;
}

route();

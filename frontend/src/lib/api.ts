export type Health = {
	status: string;
	version: string;
	catalog_version: number;
	profile_version: number;
};

export type Stats = {
	novels: number;
	cache_pages: number;
	cache_bytes: number;
	sources: { name: string; language: string; novels: number }[];
};

async function get<T>(path: string): Promise<T> {
	const response = await fetch(path);
	if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
	return (await response.json()) as T;
}

export const getHealth = () => get<Health>('/api/health');
export const getStats = () => get<Stats>('/api/stats');

export type CardStats = {
	cover_1k: number;
	cover_3k: number;
	cover_10k: number;
	kanji_pct: number;
	dialogue_pct: number;
	sample_chars: number;
};

export type Band = 'comfortable' | 'stretch' | 'hard' | 'too_hard';

/** What the learner model says about one novel; null until the placement test is taken. */
export type Personal = {
	coverage: number;
	band: Band;
	unknown_distinct: number;
	unknown_repeating: number;
	top_domains: string[];
	grow?: boolean;
};

export type NovelCard = {
	id: number;
	ncode: string;
	title: string;
	author: string | null;
	genre: string | null;
	kind: 'serial' | 'short' | null;
	status: 'ongoing' | 'completed' | 'hiatus' | null;
	chapter_count: number | null;
	length_chars: number | null;
	is_r15: boolean;
	points: number | null;
	url: string;
	last_up: string | null;
	stats: CardStats | null;
	me: Personal | null;
};

export type NovelList = { total: number; limit: number; offset: number; items: NovelCard[] };

export type UnknownWord = {
	lemma_id: number;
	lemma: string;
	pos: string;
	reading: string | null;
	gloss: string | null;
	count: number;
	rank: number | null;
	p: number;
};

export type NovelDetail = Omit<NovelCard, 'stats'> & {
	unknown_words: UnknownWord[];
	synopsis: string | null;
	keywords: string | null;
	first_up: string | null;
	site_dialogue_pct: number | null;
	stats: {
		sample_chars: number;
		tokens: number;
		unique_lemmas: number;
		cover_1k: number;
		cover_2k: number;
		cover_3k: number;
		cover_5k: number;
		cover_10k: number;
		sentence_len: number | null;
		kanji_pct: number;
		dialogue_pct: number;
		rare_load: number;
	} | null;
	curve: { words: number; cover: number }[];
	rare_words: {
		lemma: string;
		reading: string | null;
		pos: string;
		count: number;
		rank: number | null;
	}[];
	rankings: { list: string; date: string; rank: number; points: number | null }[];
};

export type Genre = { genre: string; novels: number };

export type CollectStatus = {
	novels: number;
	sampled: number;
	analysed: number;
	last_sample_at: number | null;
	hosts: { host: string; requests_today: number; requests_left: number; switched_off: boolean }[];
};

export type Sort = 'best' | 'popularity' | 'easiest' | 'updated' | 'length';

/** How much each thing counts in the ranking, 0 to 100. `grow` is the percent of slots for growth picks. */
export type Weights = {
	fit: number;
	ease: number;
	popularity: number;
	recent: number;
	length: number;
	completed: number;
	grow: number;
};
export const WEIGHT_KEYS = [
	'fit',
	'ease',
	'popularity',
	'recent',
	'length',
	'completed',
	'grow'
] as const;
const NONE: Weights = {
	fit: 0,
	ease: 0,
	popularity: 0,
	recent: 0,
	length: 0,
	completed: 0,
	grow: 0
};
/** The drop-down choices as weight sets. Keep in step with PRESETS in src/wn/api/routes/novels.py. */
export const PRESETS: Record<Sort, Weights> = {
	best: { ...NONE, fit: 100, popularity: 1, completed: 0.5, grow: 20 },
	popularity: { ...NONE, popularity: 100 },
	easiest: { ...NONE, ease: 100, popularity: 1 },
	updated: { ...NONE, recent: 100 },
	length: { ...NONE, length: 100 }
};

export type NovelQuery = {
	q?: string;
	genre?: string;
	completed?: boolean;
	hide_r15?: boolean;
	min_cover_3k?: number;
	sort?: Sort;
	band?: Band;
	w_fit?: number;
	w_ease?: number;
	w_popularity?: number;
	w_recent?: number;
	w_length?: number;
	w_completed?: number;
	w_grow?: number;
	limit?: number;
	offset?: number;
};

function query(params: Record<string, string | number | boolean | undefined>): string {
	const search = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value === undefined || value === '' || value === false) continue; // 0 is kept
		search.set(key, String(value));
	}
	const text = search.toString();
	return text ? `?${text}` : '';
}

export const listNovels = (params: NovelQuery) => get<NovelList>(`/api/novels${query(params)}`);
export const getNovel = (id: number) => get<NovelDetail>(`/api/novels/${id}`);
export const getGenres = () => get<Genre[]>('/api/genres');
export const getCollectStatus = () => get<CollectStatus>('/api/collect/status');

/** Tell the app a novel was opened, so `wn syosetu deepen` reads it first. */
export const noteOpened = (id: number) =>
	fetch(`/api/novels/${id}/open`, { method: 'POST' }).catch(() => undefined);

// --- the learner ---------------------------------------------------------------------------

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
	const response = await fetch(path, {
		method,
		headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	if (!response.ok) {
		let detail = '';
		try {
			detail = (await response.json()).detail ?? '';
		} catch {
			// no JSON body
		}
		throw new Error(`${path}: HTTP ${response.status} ${detail}`.trim());
	}
	return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export type TestStatus = {
	ready: boolean;
	problems: string[];
	test_words: number;
	ranked_words: number;
	excerpts: number;
	answers: number;
	unfinished: { id: number; kind: 'full' | 'quick' } | null;
	last: { id: number; kind: 'full' | 'quick'; finished_at: number } | null;
};

export type TestProgress = {
	kind: 'full' | 'quick';
	part: 'A' | 'B' | 'done';
	words_done: number;
	words_total: number;
	passages_done: number;
	passages_total: number;
};

export type TestItem =
	| { type: 'word'; lemma: string; pos: string; reading: string | null; domain: string | null }
	| { type: 'fake'; text: string }
	| {
			type: 'meaning';
			lemma: string;
			pos: string;
			reading: string | null;
			choices: string[];
	  }
	| {
			type: 'passage';
			excerpt_id: number;
			tokens: [string, boolean][]; // surface, can be tapped
			cloze: { index: number; choices: string[] } | null;
	  };

export type TestStep = {
	session?: number;
	item: TestItem | null;
	progress: TestProgress;
	done: boolean;
};

export type TestAnswer = {
	known?: boolean;
	choice?: number | null;
	tapped?: number[];
	rating?: 'almost_all' | 'most' | 'gist' | 'lost';
	cloze_choice?: number | null;
};

export const getTestStatus = () => get<TestStatus>('/api/test/status');
export const startTest = (kind: 'full' | 'quick') =>
	send<TestStep & { session: number }>('POST', '/api/test/start', { kind });
export const getTestStep = (session: number) => get<TestStep>(`/api/test/${session}/next`);
export const answerTest = (session: number, answer: TestAnswer) =>
	send<TestStep>('POST', `/api/test/${session}/answer`, answer);

export type DomainStrength = {
	key: string;
	name_en: string;
	name_ja: string;
	delta: number;
	delta_sd: number;
	words: number;
	share: number | null;
	low: number | null;
	high: number | null;
};

export type Profile = {
	tested: boolean;
	answers: number;
	vocabulary: number;
	vocabulary_range: [number, number];
	guess_rate: number;
	jlpt: {
		loaded: boolean;
		estimate: number | null;
		levels: { level: number; total: number; checked: number; share: number | null }[];
	};
	domains: DomainStrength[];
	weakest_domain: string | null;
	marked: { known: number; unknown: number };
	passages: { predicted: number; rating: string }[];
	feedback: {
		id: number;
		novel: string;
		title: string | null;
		felt: 'easier' | 'right' | 'harder';
		predicted: number | null;
		note: string | null;
		at: number;
	}[];
};

export const getProfile = () => get<Profile>('/api/profile');

export type WordItem = {
	lemma_id: number;
	lemma: string;
	pos: string;
	reading: string | null;
	gloss: string | null;
	rank: number;
	marked: boolean | null;
	p: number;
	domains: { domain: string; weight: number }[];
};

export type WordQuery = {
	q?: string;
	status?: 'known' | 'unknown' | 'marked' | 'any';
	domain?: string;
	limit?: number;
	offset?: number;
};

export const listWords = (params: WordQuery) =>
	get<{ total: number; items: WordItem[] }>(`/api/words${query(params)}`);
export const setWordStatus = (lemma_id: number, known: boolean | null) =>
	send<void>('PUT', '/api/words/status', { lemma_id, known });
export const setWordDomain = (
	lemma_id: number,
	domain: string,
	action: 'add' | 'remove' | 'clear'
) => send<void>('PUT', '/api/words/domains', { lemma_id, domain, action });
export const getDomains = () =>
	get<{ key: string; name_en: string; name_ja: string }[]>('/api/domains');
export const sendFeedback = (id: number, felt: 'easier' | 'right' | 'harder', note?: string) =>
	send<void>('POST', `/api/novels/${id}/feedback`, { felt, note });

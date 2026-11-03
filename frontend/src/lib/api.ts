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
};

export type NovelList = { total: number; limit: number; offset: number; items: NovelCard[] };

export type NovelDetail = Omit<NovelCard, 'stats'> & {
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

export type Sort = 'popularity' | 'easiest' | 'updated' | 'length';

export type NovelQuery = {
	q?: string;
	genre?: string;
	completed?: boolean;
	hide_r15?: boolean;
	min_cover_3k?: number;
	sort?: Sort;
	limit?: number;
	offset?: number;
};

function query(params: Record<string, string | number | boolean | undefined>): string {
	const search = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value === undefined || value === '' || value === false) continue;
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

export const percent = (value: number | null | undefined, digits = 0) =>
	value === null || value === undefined ? '–' : `${(value * 100).toFixed(digits)}%`;

/** 480000 -> "480k characters"; Syosetu counts length in characters. */
export function characters(value: number | null | undefined): string {
	if (value === null || value === undefined) return '–';
	if (value >= 10_000) return `${Math.round(value / 1000).toLocaleString('en')}k characters`;
	return `${value.toLocaleString('en')} characters`;
}

export const date = (value: string | null | undefined) => (value ? value.slice(0, 10) : '–');

export const STATUS_LABEL = { ongoing: 'Ongoing', completed: 'Completed', hiatus: 'On hiatus' };
export const RANK_LABEL: Record<string, string> = {
	daily: 'Daily',
	weekly: 'Weekly',
	monthly: 'Monthly',
	quarterly: 'Quarterly'
};

export const BAND_LABEL: Record<string, string> = {
	comfortable: 'Comfortable',
	stretch: 'Stretch',
	hard: 'Hard',
	too_hard: 'Too hard'
};

/** Short guidance under each band's name. */
export const BAND_HINT: Record<string, string> = {
	comfortable: 'reads with almost no lookups',
	stretch: 'about one unknown word per two lines',
	hard: 'readable with a dictionary at hand',
	too_hard: 'too many unknown words to enjoy'
};

export const JLPT_LABEL = (level: number | null | undefined) =>
	level ? `about N${level}` : 'below N5';

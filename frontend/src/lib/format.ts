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

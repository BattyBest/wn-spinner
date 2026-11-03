/** Which language the app is showing. Kept in this browser; changing it reloads the page. */
export type LangCode = 'ja' | 'zh';

export type LangInfo = {
	code: LangCode;
	label: string; // the switch's text
	htmlLang: string; // lang="" for text in this language
	site: string; // where the novels come from
	level: string; // JLPT or HSK
	command: string; // the CLI group that collects it
	words: string; // "kanji" or "hanzi"
};

export const LANGS: Record<LangCode, LangInfo> = {
	ja: {
		code: 'ja',
		label: '日本語',
		htmlLang: 'ja',
		site: 'Syosetu',
		level: 'JLPT',
		command: 'syosetu',
		words: 'Kanji'
	},
	zh: {
		code: 'zh',
		label: '中文',
		htmlLang: 'zh-Hans',
		site: 'jjwxc',
		level: 'HSK',
		command: 'jjwxc',
		words: 'Hanzi'
	}
};

const KEY = 'wn-lang';

export function getLang(): LangCode {
	try {
		const saved = localStorage.getItem(KEY);
		if (saved === 'ja' || saved === 'zh') return saved;
	} catch {
		// storage blocked: fall back to Japanese
	}
	return 'ja';
}

export const current = (): LangInfo => LANGS[getLang()];

export function setLang(code: LangCode): void {
	try {
		localStorage.setItem(KEY, code);
	} catch {
		// not remembered, but the reload below still shows the choice for this visit
	}
	location.reload();
}

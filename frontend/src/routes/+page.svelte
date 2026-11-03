<script lang="ts">
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import BandBadge from '#lib/BandBadge.svelte';
	import CoverBar from '#lib/CoverBar.svelte';
	import {
		getCollectStatus,
		getDomains,
		getGenres,
		getTestStatus,
		listNovels,
		type Band,
		type CollectStatus,
		type Genre,
		type NovelList,
		type Sort,
		type Weights,
		PRESETS,
		WEIGHT_KEYS
	} from '#lib/api';
	import { BAND_HINT, BAND_LABEL, STATUS_LABEL, characters } from '#lib/format';
	import { current } from '#lib/lang';

	const L = current();

	const PAGE = 24;
	const SORTS: { value: Sort; label: string }[] = [
		{ value: 'best', label: 'Best for me' },
		{ value: 'popularity', label: 'Most popular' },
		{ value: 'easiest', label: 'Easiest first' },
		{ value: 'updated', label: 'Recently updated' },
		{ value: 'length', label: 'Longest' }
	];
	const WEIGHT_LABELS: Record<keyof Weights, { label: string; hint: string }> = {
		fit: { label: 'Fits my level', hint: 'Close to a comfortable stretch for you' },
		ease: { label: 'Easy vocabulary', hint: 'The 3,000 most common words cover more of it' },
		popularity: { label: 'Popular', hint: `More ${L.site} points` },
		recent: { label: 'Recently updated', hint: 'Newer updates first' },
		length: { label: 'Long', hint: 'Longer novels first' },
		completed: { label: 'Completed', hint: 'A bonus for finished novels' },
		grow: { label: 'Growth picks', hint: 'Share of slots for your weakest topic (percent)' }
	};
	const NEEDS_TEST = ['fit', 'grow'];
	const LENGTHS = [
		{ value: '', label: 'Any length', min: undefined, max: undefined },
		{ value: 'short', label: 'Short story (under 20k)', min: undefined, max: 20_000 },
		{ value: 'medium', label: '20k to 200k', min: 20_000, max: 200_000 },
		{ value: 'long', label: 'Over 200k', min: 200_000, max: undefined }
	];

	let q = $state('');
	let genre = $state('');
	let length = $state('');
	let completed = $state(false);
	let showR15 = $state(false); // R15 works are hidden unless asked for
	let minCover = $state(0);
	let weights = $state<Weights>({ ...PRESETS.popularity });
	let band = $state<Band | ''>('');
	let offset = $state(0);
	let tested = $state(false); // the placement test has been taken
	let domainNames = $state<Record<string, string>>({});

	let list = $state<NovelList | null>(null);
	let genres = $state<Genre[]>([]);
	let status = $state<CollectStatus | null>(null);
	let failed = $state(false);
	let ready = $state(false);
	let showFilters = $state(false);

	const activeFilters = $derived(
		[q, genre, length, completed, showR15, minCover > 0, band].filter(Boolean).length
	);
	const sorts = $derived(tested ? SORTS : SORTS.filter((s) => s.value !== 'best'));
	const defaultSort = $derived<Sort>(tested ? 'best' : 'popularity');
	/** The drop-down shows a preset while the weights match it, and "Custom mix" otherwise. */
	const sort = $derived<Sort | 'custom'>(
		sorts.find((s) => WEIGHT_KEYS.every((k) => weights[k] === PRESETS[s.value][k]))?.value ??
			'custom'
	);
	const setPreset = (value: string) => {
		if (value in PRESETS) weights = { ...PRESETS[value as Sort] };
		offset = 0;
	};

	onMount(async () => {
		try {
			tested = (await getTestStatus()).answers > 0;
		} catch {
			tested = false;
		}
		const p = new URLSearchParams(window.location.search);
		q = p.get('q') ?? '';
		genre = p.get('genre') ?? '';
		length = p.get('length') ?? '';
		completed = p.get('completed') === '1';
		showR15 = p.get('r15') === 'show';
		minCover = Number(p.get('cover') ?? 0) || 0;
		band = (['comfortable', 'stretch', 'hard', 'too_hard'].find((b) => b === p.get('band')) ??
			'') as Band | '';
		const preset = (sorts.find((s) => s.value === p.get('sort'))?.value ?? defaultSort) as Sort;
		weights = { ...PRESETS[preset] };
		if (WEIGHT_KEYS.some((k) => p.has(`w_${k}`))) {
			for (const k of WEIGHT_KEYS) {
				const v = Number(p.get(`w_${k}`));
				const ok = Number.isFinite(v) ? Math.min(100, Math.max(0, v)) : 0;
				weights[k] = tested || !NEEDS_TEST.includes(k) ? ok : 0;
			}
		}
		offset = Number(p.get('offset') ?? 0) || 0;
		ready = true;
		getGenres()
			.then((g) => (genres = g))
			.catch(() => undefined);
		getDomains()
			.then((d) => (domainNames = Object.fromEntries(d.map((x) => [x.key, x.name_en]))))
			.catch(() => undefined);
		getCollectStatus()
			.then((s) => (status = s))
			.catch(() => undefined);
	});

	// Reload whenever a filter changes, and keep the address bar in step so a view can be bookmarked.
	let timer: ReturnType<typeof setTimeout> | undefined;
	$effect(() => {
		if (!ready) return;
		const span = LENGTHS.find((l) => l.value === length);
		const query = {
			q: q.trim() || undefined,
			genre: genre || undefined,
			completed,
			hide_r15: !showR15,
			min_cover_3k: minCover > 0 ? minCover / 100 : undefined,
			min_length: span?.min,
			max_length: span?.max,
			...(sort === 'custom'
				? {
						w_fit: weights.fit,
						w_ease: weights.ease,
						w_popularity: weights.popularity,
						w_recent: weights.recent,
						w_length: weights.length,
						w_completed: weights.completed,
						w_grow: weights.grow
					}
				: { sort }),
			band: band || undefined,
			limit: PAGE,
			offset
		};
		const url = new URLSearchParams();
		if (q.trim()) url.set('q', q.trim());
		if (genre) url.set('genre', genre);
		if (length) url.set('length', length);
		if (completed) url.set('completed', '1');
		if (showR15) url.set('r15', 'show');
		if (minCover > 0) url.set('cover', String(minCover));
		if (sort === 'custom') for (const k of WEIGHT_KEYS) url.set(`w_${k}`, String(weights[k]));
		else if (sort !== defaultSort) url.set('sort', sort);
		if (band) url.set('band', band);
		if (offset) url.set('offset', String(offset));
		clearTimeout(timer);
		timer = setTimeout(async () => {
			try {
				list = await listNovels(query);
				failed = false;
				replaceState(url.size ? `?${url}` : window.location.pathname, {});
			} catch {
				failed = true;
			}
		}, 150);
	});

	/** Any filter change goes back to the first page. */
	const changed = () => (offset = 0);
	const clear = () => {
		q = genre = length = '';
		band = '';
		completed = showR15 = false;
		minCover = offset = 0;
		weights = { ...PRESETS[defaultSort] };
	};
	const last = $derived(list ? Math.min(list.offset + list.items.length, list.total) : 0);
</script>

<svelte:head><title>Discover · wn-spinner</title></svelte:head>

<h1 class="text-2xl font-semibold tracking-tight">Discover</h1>
<p class="mt-2 text-muted">
	{L.code === 'zh' ? 'Chinese web novels from jjwxc.' : 'Japanese web novels from Syosetu.'}
	{#if tested}
		Each card shows how much of the text you are expected to know, and "Best for me" puts the novels
		closest to a comfortable stretch first.
	{:else}
		The bar on each card shows how much of the text the 3,000 most common words cover, a stand-in
		for difficulty until your own level is measured.
	{/if}
</p>

{#if ready && !tested}
	<div class="mt-4 rounded-xl border border-line bg-surface p-4 text-sm">
		<a href="/test/" class="font-medium text-accent underline">Take the placement test</a>
		<span class="text-muted">
			(about 10 minutes) to see how each novel fits your level and get recommendations.
		</span>
	</div>
{/if}

<div class="mt-5 flex gap-2 md:hidden">
	<button
		type="button"
		class="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium"
		aria-expanded={showFilters}
		aria-controls="filters"
		onclick={() => (showFilters = !showFilters)}
	>
		Filters{activeFilters ? ` (${activeFilters})` : ''}
	</button>
</div>

<form
	id="filters"
	class="mt-4 grid gap-3 rounded-xl border border-line bg-surface p-4 sm:grid-cols-2 md:mt-5 md:grid {showFilters
		? 'grid'
		: 'hidden'}"
	onsubmit={(e) => e.preventDefault()}
	aria-label="Filters"
>
	<label class="text-sm sm:col-span-2">
		<span class="text-muted">Search title or author</span>
		<input
			type="search"
			bind:value={q}
			oninput={changed}
			class="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2"
		/>
	</label>
	<label class="text-sm">
		<span class="text-muted">Genre</span>
		<select
			bind:value={genre}
			onchange={changed}
			class="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2"
		>
			<option value="">All genres</option>
			{#each genres as g (g.genre)}
				<option value={g.genre}>{g.genre} ({g.novels})</option>
			{/each}
		</select>
	</label>
	<label class="text-sm">
		<span class="text-muted">Length</span>
		<select
			bind:value={length}
			onchange={changed}
			class="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2"
		>
			{#each LENGTHS as l (l.value)}
				<option value={l.value}>{l.label}</option>
			{/each}
		</select>
	</label>
	<label class="text-sm">
		<span class="text-muted">Sort by (preset)</span>
		<select
			value={sort}
			onchange={(e) => setPreset(e.currentTarget.value)}
			class="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2"
		>
			{#each sorts as s (s.value)}
				<option value={s.value}>{s.label}</option>
			{/each}
			{#if sort === 'custom'}<option value="custom">Custom mix</option>{/if}
		</select>
	</label>
	{#if tested}
		<label class="text-sm">
			<span class="text-muted">Fit for me</span>
			<select
				bind:value={band}
				onchange={changed}
				class="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2"
			>
				<option value="">Any, without "too hard"</option>
				{#each ['comfortable', 'stretch', 'hard', 'too_hard'] as b (b)}
					<option value={b}>{BAND_LABEL[b]}: {BAND_HINT[b]}</option>
				{/each}
			</select>
		</label>
	{/if}
	<label class="text-sm">
		<span class="text-muted">Top 3,000 words cover at least: {minCover}%</span>
		<input
			type="range"
			min="0"
			max="100"
			step="5"
			bind:value={minCover}
			oninput={changed}
			class="mt-2 w-full accent-accent"
		/>
	</label>
	<details class="text-sm sm:col-span-2" open={sort === 'custom'}>
		<summary class="cursor-pointer font-medium">Ranking weights</summary>
		<p class="mt-1 text-muted">
			How much each thing counts, 0 to 100. The sort preset above just sets these for you.
		</p>
		<div class="mt-2 grid gap-x-5 gap-y-2 sm:grid-cols-2">
			{#each WEIGHT_KEYS as k (k)}
				{@const off = !tested && NEEDS_TEST.includes(k)}
				<label class={off ? 'opacity-50' : ''} title={off ? 'Take the placement test first' : ''}>
					<span class="text-muted"
						>{WEIGHT_LABELS[k].label}: <strong class="text-ink">{weights[k]}</strong></span
					>
					<input
						type="range"
						min="0"
						max="100"
						step="0.5"
						disabled={off}
						bind:value={weights[k]}
						oninput={changed}
						aria-describedby="hint-{k}"
						class="mt-1 w-full accent-accent"
					/>
					<span id="hint-{k}" class="block text-xs text-muted">{WEIGHT_LABELS[k].hint}</span>
				</label>
			{/each}
		</div>
	</details>
	<div class="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm sm:col-span-2">
		<label class="flex items-center gap-2">
			<input type="checkbox" bind:checked={completed} onchange={changed} class="accent-accent" />
			Completed only
		</label>
		<label class="flex items-center gap-2">
			<input type="checkbox" bind:checked={showR15} onchange={changed} class="accent-accent" />
			{L.code === 'zh' ? 'Show mature books' : 'Show R15 works'}
		</label>
		{#if activeFilters}
			<button type="button" class="text-accent underline" onclick={clear}>Clear filters</button>
		{/if}
	</div>
</form>

<section class="mt-6" aria-live="polite">
	{#if failed}
		<p class="rounded-xl border border-line bg-surface p-5 text-sm text-bad">
			Can't reach the API. Start it with <code class="font-mono">make run</code>.
		</p>
	{:else if !list}
		<p class="text-sm text-muted">Loading…</p>
	{:else if list.total === 0}
		{#if status && status.novels === 0}
			<div class="rounded-xl border border-dashed border-line bg-surface p-5">
				<p class="text-sm font-medium">No novels collected yet</p>
				<p class="mt-1 text-sm text-muted">
					Run <code class="font-mono">uv run wn {L.command} run</code> in a terminal. It saves rankings
					and metadata first, so this page fills within seconds, then reads chapters in the background.
				</p>
			</div>
		{:else if tested && sort === 'best' && !band}
			<p class="text-sm text-muted">
				No novel is within your range yet. Choose Hard or Too hard under "Fit for me" to see what is
				close, or collect more novels with <code class="font-mono">uv run wn {L.command} run</code>.
			</p>
		{:else}
			<p class="text-sm text-muted">No novels match these filters.</p>
		{/if}
	{:else}
		<p class="text-sm text-muted">
			Showing {list.offset + 1}–{last} of {list.total}
			{#if status && status.analysed < status.novels}
				· {status.analysed} of {status.novels} analysed so far
			{/if}
		</p>
		<ul class="mt-3 grid gap-3">
			{#each list.items as novel (novel.id)}
				<li class="rounded-xl border border-line bg-surface p-4">
					<div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
						<h2 class="text-base font-semibold">
							<a href="/novel/?id={novel.id}" class="hover:text-accent hover:underline">
								{novel.title}
							</a>
						</h2>
						<a
							href={novel.url}
							target="_blank"
							rel="noopener noreferrer"
							class="text-sm font-medium text-accent hover:underline"
						>
							Read on {L.site} ↗
						</a>
					</div>
					<p class="mt-1 text-sm text-muted">
						{novel.author ?? 'Unknown author'}
						{#if novel.genre}· {novel.genre}{/if}
					</p>
					<p class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
						<span>{novel.kind === 'short' ? 'Short story' : 'Serial'}</span>
						<span>{characters(novel.length_chars)}</span>
						{#if novel.kind !== 'short' && novel.chapter_count}
							<span>{novel.chapter_count} chapters</span>
						{/if}
						{#if novel.status}<span>{STATUS_LABEL[novel.status]}</span>{/if}
						{#if novel.is_r15}
							<span class="rounded bg-line px-1.5 font-medium text-ink">R15</span>
						{/if}
						{#if novel.is_mature}
							<span class="rounded bg-line px-1.5 font-medium text-ink">Mature</span>
						{/if}
						{#if novel.favourites}<span>{novel.favourites.toLocaleString('en')} favourites</span
							>{/if}
					</p>
					<div class="mt-3">
						{#if novel.me}
							<div class="flex flex-wrap items-center gap-2">
								<BandBadge band={novel.me.band} coverage={novel.me.coverage} />
								{#if novel.me.grow}
									<span class="rounded-full border border-line px-2 py-0.5 text-xs text-muted">
										Grow pick
									</span>
								{/if}
							</div>
							<p class="mt-2 text-xs text-muted">
								About {novel.me.unknown_distinct.toLocaleString('en')} unknown words,
								{novel.me.unknown_repeating} of them repeat 5 or more times
								{#if novel.me.top_domains.length}
									· mostly {novel.me.top_domains
										.map((d) => domainNames[d] ?? d)
										.join(' and ')
										.toLowerCase()}
								{/if}
							</p>
						{:else if novel.stats}
							<CoverBar value={novel.stats.cover_3k} label="Covered by the top 3,000 words" />
						{:else}
							<p class="text-xs text-muted">Not analysed yet</p>
						{/if}
					</div>
				</li>
			{/each}
		</ul>
		<nav class="mt-5 flex items-center justify-between" aria-label="Pages">
			<button
				type="button"
				class="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium disabled:opacity-40"
				disabled={list.offset === 0}
				onclick={() => (offset = Math.max(0, list!.offset - PAGE))}
			>
				Previous
			</button>
			<button
				type="button"
				class="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium disabled:opacity-40"
				disabled={last >= list.total}
				onclick={() => (offset = list!.offset + PAGE)}
			>
				Next
			</button>
		</nav>
	{/if}
</section>

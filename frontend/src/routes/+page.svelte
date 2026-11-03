<script lang="ts">
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import CoverBar from '#lib/CoverBar.svelte';
	import {
		getCollectStatus,
		getGenres,
		listNovels,
		type CollectStatus,
		type Genre,
		type NovelList,
		type Sort
	} from '#lib/api';
	import { STATUS_LABEL, characters } from '#lib/format';

	const PAGE = 24;
	const SORTS: { value: Sort; label: string }[] = [
		{ value: 'popularity', label: 'Most popular' },
		{ value: 'easiest', label: 'Easiest first' },
		{ value: 'updated', label: 'Recently updated' },
		{ value: 'length', label: 'Longest' }
	];
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
	let sort = $state<Sort>('popularity');
	let offset = $state(0);

	let list = $state<NovelList | null>(null);
	let genres = $state<Genre[]>([]);
	let status = $state<CollectStatus | null>(null);
	let failed = $state(false);
	let ready = $state(false);
	let showFilters = $state(false);

	const activeFilters = $derived(
		[q, genre, length, completed, showR15, minCover > 0].filter(Boolean).length
	);

	onMount(() => {
		const p = new URLSearchParams(window.location.search);
		q = p.get('q') ?? '';
		genre = p.get('genre') ?? '';
		length = p.get('length') ?? '';
		completed = p.get('completed') === '1';
		showR15 = p.get('r15') === 'show';
		minCover = Number(p.get('cover') ?? 0) || 0;
		sort = (SORTS.find((s) => s.value === p.get('sort'))?.value ?? 'popularity') as Sort;
		offset = Number(p.get('offset') ?? 0) || 0;
		ready = true;
		getGenres()
			.then((g) => (genres = g))
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
			sort,
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
		if (sort !== 'popularity') url.set('sort', sort);
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
		completed = showR15 = false;
		minCover = offset = 0;
	};
	const last = $derived(list ? Math.min(list.offset + list.items.length, list.total) : 0);
</script>

<svelte:head><title>Discover · wn-spinner</title></svelte:head>

<h1 class="text-2xl font-semibold tracking-tight">Discover</h1>
<p class="mt-2 text-muted">
	Japanese web novels from Syosetu. The bar on each card shows how much of the text the 3,000 most
	common words cover, a stand-in for difficulty until your own level is measured in a later
	milestone.
</p>

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
		<span class="text-muted">Sort by</span>
		<select
			bind:value={sort}
			onchange={changed}
			class="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2"
		>
			{#each SORTS as s (s.value)}
				<option value={s.value}>{s.label}</option>
			{/each}
		</select>
	</label>
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
	<div class="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm sm:col-span-2">
		<label class="flex items-center gap-2">
			<input type="checkbox" bind:checked={completed} onchange={changed} class="accent-accent" />
			Completed only
		</label>
		<label class="flex items-center gap-2">
			<input type="checkbox" bind:checked={showR15} onchange={changed} class="accent-accent" />
			Show R15 works
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
					Run <code class="font-mono">uv run wn syosetu run</code> in a terminal. It saves rankings and
					metadata first, so this page fills within seconds, then reads chapters in the background.
				</p>
			</div>
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
							Read on Syosetu ↗
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
					</p>
					<div class="mt-3">
						{#if novel.stats}
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

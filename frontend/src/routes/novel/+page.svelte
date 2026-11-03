<script lang="ts">
	import { onMount } from 'svelte';
	import CoverageCurve from '#lib/CoverageCurve.svelte';
	import { getNovel, noteOpened, type NovelDetail } from '#lib/api';
	import { RANK_LABEL, STATUS_LABEL, characters, date, percent } from '#lib/format';

	let novel = $state<NovelDetail | null>(null);
	let missing = $state(false);
	let failed = $state(false);

	onMount(async () => {
		const id = Number(new URLSearchParams(window.location.search).get('id'));
		if (!id) {
			missing = true;
			return;
		}
		try {
			novel = await getNovel(id);
			document.title = `${novel.title} · wn-spinner`;
			noteOpened(id);
		} catch (error) {
			if (String(error).includes('HTTP 404')) missing = true;
			else failed = true;
		}
	});

	const keywords = $derived(novel?.keywords?.split(/\s+/).filter(Boolean) ?? []);
</script>

<svelte:head><title>Novel · wn-spinner</title></svelte:head>

{#if missing}
	<h1 class="text-2xl font-semibold tracking-tight">Novel detail</h1>
	<p class="mt-2 text-muted">
		Pick a novel on <a href="/" class="text-accent underline">Discover</a> to see its details here.
	</p>
{:else if failed}
	<p class="rounded-xl border border-line bg-surface p-5 text-sm text-bad">
		Can't reach the API. Start it with <code class="font-mono">make run</code>.
	</p>
{:else if !novel}
	<p class="text-sm text-muted">Loading…</p>
{:else}
	<a href="/" class="text-sm text-accent hover:underline">← Back to Discover</a>
	<h1 class="mt-3 text-2xl font-semibold tracking-tight">{novel.title}</h1>
	<p class="mt-1 text-muted">
		{novel.author ?? 'Unknown author'}{#if novel.genre}
			· {novel.genre}{/if}
	</p>
	<p class="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
		<span>{novel.kind === 'short' ? 'Short story' : 'Serial'}</span>
		<span>{characters(novel.length_chars)}</span>
		{#if novel.kind !== 'short' && novel.chapter_count}
			<span>{novel.chapter_count} chapters</span>
		{/if}
		{#if novel.status}<span>{STATUS_LABEL[novel.status]}</span>{/if}
		<span>Updated {date(novel.last_up)}</span>
		{#if novel.is_r15}<span class="rounded bg-line px-1.5 font-medium text-ink">R15</span>{/if}
	</p>

	<a
		href={novel.url}
		target="_blank"
		rel="noopener noreferrer"
		class="mt-5 inline-block rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-accent-ink"
	>
		Read on Syosetu ↗
	</a>

	{#if novel.synopsis}
		<section class="mt-8">
			<h2 class="text-sm font-semibold">Synopsis</h2>
			<p class="mt-2 whitespace-pre-line">{novel.synopsis}</p>
		</section>
	{/if}

	{#if keywords.length}
		<ul class="mt-4 flex flex-wrap gap-2" aria-label="Keywords">
			{#each keywords as word (word)}
				<li class="rounded-full border border-line bg-surface px-2.5 py-0.5 text-xs text-muted">
					{word}
				</li>
			{/each}
		</ul>
	{/if}

	<section class="mt-8">
		<h2 class="text-sm font-semibold">Vocabulary</h2>
		{#if novel.stats}
			<p class="mt-1 text-sm text-muted">
				Measured on {novel.stats.sample_chars.toLocaleString('en')} characters from the opening chapters.
				Word ranks come from the novels collected here, so they sharpen as the catalog grows.
			</p>
			<div class="mt-4 rounded-xl border border-line bg-surface p-4">
				<CoverageCurve points={novel.curve} />
			</div>
			<dl class="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
				<div class="rounded-xl border border-line bg-surface p-3">
					<dt class="text-muted">Top 1,000 words cover</dt>
					<dd class="text-lg font-semibold">{percent(novel.stats.cover_1k)}</dd>
				</div>
				<div class="rounded-xl border border-line bg-surface p-3">
					<dt class="text-muted">Top 3,000 words cover</dt>
					<dd class="text-lg font-semibold">{percent(novel.stats.cover_3k)}</dd>
				</div>
				<div class="rounded-xl border border-line bg-surface p-3">
					<dt class="text-muted">Top 10,000 words cover</dt>
					<dd class="text-lg font-semibold">{percent(novel.stats.cover_10k)}</dd>
				</div>
				<div class="rounded-xl border border-line bg-surface p-3">
					<dt class="text-muted">Different words</dt>
					<dd class="text-lg font-semibold">{novel.stats.unique_lemmas.toLocaleString('en')}</dd>
				</div>
				<div class="rounded-xl border border-line bg-surface p-3">
					<dt class="text-muted">Rare words that repeat</dt>
					<dd class="text-lg font-semibold">{novel.stats.rare_load}</dd>
				</div>
				<div class="rounded-xl border border-line bg-surface p-3">
					<dt class="text-muted">Average sentence</dt>
					<dd class="text-lg font-semibold">
						{novel.stats.sentence_len ? `${novel.stats.sentence_len.toFixed(0)} chars` : '–'}
					</dd>
				</div>
				<div class="rounded-xl border border-line bg-surface p-3">
					<dt class="text-muted">Kanji</dt>
					<dd class="text-lg font-semibold">{percent(novel.stats.kanji_pct)}</dd>
				</div>
				<div class="rounded-xl border border-line bg-surface p-3">
					<dt class="text-muted">Dialogue (sample)</dt>
					<dd class="text-lg font-semibold">{percent(novel.stats.dialogue_pct)}</dd>
				</div>
				<div class="rounded-xl border border-line bg-surface p-3">
					<dt class="text-muted">Dialogue (Syosetu)</dt>
					<dd class="text-lg font-semibold">
						{novel.site_dialogue_pct === null ? '–' : `${novel.site_dialogue_pct}%`}
					</dd>
				</div>
			</dl>
		{:else}
			<p class="mt-2 text-sm text-muted">
				Not analysed yet. Run <code class="font-mono">uv run wn syosetu sample</code> to read this novel's
				opening chapters.
			</p>
		{/if}
	</section>

	{#if novel.rare_words.length}
		<section class="mt-8">
			<h2 class="text-sm font-semibold">Words worth learning first</h2>
			<p class="mt-1 text-sm text-muted">
				Frequent here and outside the common 5,000, most frequent first. Names are left out.
			</p>
			<ul class="mt-3 grid gap-2 sm:grid-cols-2">
				{#each novel.rare_words as word (word.lemma + word.pos)}
					<li
						class="flex items-baseline justify-between gap-3 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
					>
						<span>
							<span class="font-medium">{word.lemma}</span>
							{#if word.reading && word.reading !== word.lemma}
								<span class="text-muted"> {word.reading}</span>
							{/if}
						</span>
						<span class="text-xs text-muted">×{word.count}</span>
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	{#if novel.rankings.length}
		<section class="mt-8">
			<h2 class="text-sm font-semibold">On the Syosetu rankings</h2>
			<ul class="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted">
				{#each novel.rankings as r (r.list)}
					<li>
						{RANK_LABEL[r.list] ?? r.list}: <strong class="text-ink">#{r.rank}</strong> on {r.date}
					</li>
				{/each}
			</ul>
		</section>
	{/if}
{/if}

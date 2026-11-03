<script lang="ts">
	import { onMount } from 'svelte';
	import BandBadge from '#lib/BandBadge.svelte';
	import CoverageCurve from '#lib/CoverageCurve.svelte';
	import {
		getNovel,
		noteOpened,
		sendFeedback,
		setWordStatus,
		type NovelDetail,
		type UnknownWord
	} from '#lib/api';
	import { BAND_HINT, RANK_LABEL, STATUS_LABEL, characters, date, percent } from '#lib/format';

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
			rows = novel.unknown_words;
			document.title = `${novel.title} · wn-spinner`;
			noteOpened(id);
		} catch (error) {
			if (String(error).includes('HTTP 404')) missing = true;
			else failed = true;
		}
	});

	let felt = $state<'easier' | 'right' | 'harder' | null>(null);
	let note = $state('');
	let sent = $state(false);
	let marked = $state<Record<number, boolean | null>>({});
	// The to-mark list is frozen while you work through it, so rows never jump under the cursor.
	// Marked rows stay in place (dimmed, with undo) until you press "Remove marked words".
	let rows = $state<UnknownWord[]>([]);
	const pending = $derived(rows.filter((w) => marked[w.lemma_id] != null).length);

	async function reload(compact = false) {
		if (!novel) return;
		const fresh = await getNovel(novel.id);
		if (compact) {
			rows = fresh.unknown_words;
			marked = {};
		}
		novel = { ...fresh, unknown_words: rows };
	}

	async function mark(word: UnknownWord, known: boolean) {
		// Pressing the active choice again undoes it.
		const next = marked[word.lemma_id] === known ? null : known;
		await setWordStatus(word.lemma_id, next);
		marked = { ...marked, [word.lemma_id]: next };
		await reload();
	}

	async function giveFeedback() {
		if (!novel || !felt) return;
		await sendFeedback(novel.id, felt, note);
		sent = true;
	}

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

	{#if novel.me}
		<section class="mt-8">
			<h2 class="text-sm font-semibold">For you</h2>
			<div class="mt-2 rounded-xl border border-line bg-surface p-4">
				<BandBadge band={novel.me.band} coverage={novel.me.coverage} />
				<p class="mt-2 text-sm text-muted first-letter:uppercase">
					{BAND_HINT[novel.me.band]}. You are expected to know {percent(novel.me.coverage, 1)} of the
					words in the sample, about {novel.me.unknown_distinct.toLocaleString('en')} distinct words you
					probably don't know; {novel.me.unknown_repeating} of them repeat 5 or more times, so they are
					worth learning first.
				</p>
			</div>
			{#if rows.length}
				<h3 class="mt-5 text-sm font-semibold">Words you probably don't know</h3>
				<p class="mt-1 text-sm text-muted">
					Most frequent first. Tell the app which ones you know and your predictions improve. Marked
					words stay where they are, so nothing moves while you click; press the button again to
					undo.
				</p>
				{#if pending}
					<button
						type="button"
						class="mt-2 rounded-lg border border-line px-3 py-1.5 text-xs font-medium"
						onclick={() => reload(true)}>Remove {pending} marked from the list</button
					>
				{/if}
				<ul class="mt-3 grid gap-2">
					{#each rows as word (word.lemma_id)}
						<li
							class="rounded-lg border border-line bg-surface px-3 py-2 text-sm {marked[
								word.lemma_id
							] != null
								? 'opacity-60'
								: ''}"
						>
							<div class="flex flex-wrap items-baseline justify-between gap-x-3">
								<span>
									<span class="font-medium" lang="ja">{word.lemma}</span>
									{#if word.reading && word.reading !== word.lemma}
										<span class="text-muted" lang="ja"> {word.reading}</span>
									{/if}
									<span class="text-muted"> · {word.gloss ?? 'no gloss'}</span>
								</span>
								<span class="text-xs text-muted">×{word.count}</span>
							</div>
							<div class="mt-2 flex gap-2">
								<button
									type="button"
									aria-pressed={marked[word.lemma_id] === true}
									class="rounded-lg border border-line px-2.5 py-1 text-xs font-medium aria-pressed:border-good aria-pressed:text-good"
									onclick={() => mark(word, true)}>I know it</button
								>
								<button
									type="button"
									aria-pressed={marked[word.lemma_id] === false}
									class="rounded-lg border border-line px-2.5 py-1 text-xs font-medium aria-pressed:border-bad aria-pressed:text-bad"
									onclick={() => mark(word, false)}>I don't</button
								>
							</div>
						</li>
					{/each}
				</ul>
			{/if}
		</section>
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

	{#if novel.me}
		<section class="mt-8">
			<h2 class="text-sm font-semibold">How did it feel?</h2>
			{#if sent}
				<p class="mt-2 text-sm text-muted">
					Thanks, saved. You can see it with the prediction on your <a
						href="/profile/"
						class="text-accent underline">profile</a
					>.
				</p>
			{:else}
				<p class="mt-1 text-sm text-muted">
					After you have tried it on Syosetu: was it easier or harder than predicted? This is how we
					check the model.
				</p>
				<div class="mt-3 flex flex-wrap gap-2" role="group" aria-label="How it felt">
					{#each [['easier', 'Easier'], ['right', 'About right'], ['harder', 'Harder']] as [value, label] (value)}
						<button
							type="button"
							aria-pressed={felt === value}
							class="rounded-lg border border-line px-3 py-2 text-sm font-medium aria-pressed:border-accent aria-pressed:text-accent"
							onclick={() => (felt = value as 'easier' | 'right' | 'harder')}>{label}</button
						>
					{/each}
				</div>
				<label class="mt-3 block text-sm">
					<span class="text-muted">Note (optional)</span>
					<input
						type="text"
						bind:value={note}
						maxlength="500"
						class="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2"
					/>
				</label>
				<button
					type="button"
					disabled={!felt}
					class="mt-3 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-ink disabled:opacity-50"
					onclick={giveFeedback}>Save</button
				>
			{/if}
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

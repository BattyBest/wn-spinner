<script lang="ts">
	import { onMount } from 'svelte';
	import DomainChart from '#lib/DomainChart.svelte';
	import {
		getDomains,
		getProfile,
		listWords,
		setWordDomain,
		setWordStatus,
		type Profile,
		type WordItem
	} from '#lib/api';
	import { levelLabel, levelName, percent } from '#lib/format';
	import { current } from '#lib/lang';

	const L = current();

	let profile = $state<Profile | null>(null);
	let failed = $state(false);
	let domains = $state<{ key: string; name_en: string }[]>([]);

	let q = $state('');
	let status = $state<'any' | 'known' | 'unknown' | 'marked'>('any');
	let domain = $state('');
	let offset = $state(0);
	let words = $state<{ total: number; items: WordItem[] } | null>(null);
	let editing = $state<number | null>(null);
	const PAGE = 20;

	async function load() {
		try {
			profile = await getProfile();
		} catch {
			failed = true;
		}
	}

	onMount(() => {
		load();
		getDomains()
			.then((d) => (domains = d))
			.catch(() => undefined);
	});

	let timer: ReturnType<typeof setTimeout> | undefined;
	$effect(() => {
		const query = {
			q: q.trim() || undefined,
			status,
			domain: domain || undefined,
			offset,
			limit: PAGE
		};
		clearTimeout(timer);
		timer = setTimeout(() => {
			listWords(query)
				.then((w) => (words = w))
				.catch(() => undefined);
		}, 150);
	});

	async function mark(word: WordItem, known: boolean | null) {
		await setWordStatus(word.lemma_id, known);
		await Promise.all([
			load(),
			listWords({
				q: q.trim() || undefined,
				status,
				domain: domain || undefined,
				offset,
				limit: PAGE
			}).then((w) => (words = w))
		]);
	}

	async function fix(word: WordItem, key: string, action: 'add' | 'remove' | 'clear') {
		await setWordDomain(word.lemma_id, key, action);
		words = await listWords({
			q: q.trim() || undefined,
			status,
			domain: domain || undefined,
			offset,
			limit: PAGE
		});
	}

	const nameOf = (key: string) => domains.find((d) => d.key === key)?.name_en ?? key;
	const FELT = {
		easier: 'Easier than predicted',
		right: 'About right',
		harder: 'Harder than predicted'
	};
	const when = (seconds: number) => new Date(seconds * 1000).toLocaleDateString('en');
</script>

<svelte:head><title>My profile · wn-spinner</title></svelte:head>

<h1 class="text-2xl font-semibold tracking-tight">My profile</h1>

{#if failed}
	<p class="mt-4 rounded-xl border border-line bg-surface p-5 text-sm text-bad">
		Can't reach the API. Start it with <code class="font-mono">make run</code>.
	</p>
{:else if !profile}
	<p class="mt-3 text-sm text-muted">Loading…</p>
{:else if !profile.tested}
	<p class="mt-2 text-muted">
		Your level, your strength in each vocabulary domain, and the words you have marked.
	</p>
	<div class="mt-6 rounded-xl border border-dashed border-line bg-surface p-5">
		<p class="text-sm font-medium">No level measured yet</p>
		<p class="mt-1 text-sm text-muted">
			Take the <a href="/test/" class="text-accent underline">placement test</a> to build your profile.
		</p>
	</div>
{:else}
	<p class="mt-2 text-muted">Based on {profile.answers.toLocaleString('en')} answers.</p>
	<dl class="mt-5 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
		<div class="rounded-xl border border-line bg-surface p-4">
			<dt class="text-muted">Vocabulary</dt>
			<dd class="text-2xl font-semibold">about {profile.vocabulary.toLocaleString('en')}</dd>
			<dd class="text-xs text-muted">
				{profile.vocabulary_range[0].toLocaleString('en')} to {profile.vocabulary_range[1].toLocaleString(
					'en'
				)}
			</dd>
		</div>
		<div class="rounded-xl border border-line bg-surface p-4">
			<dt class="text-muted">{profile.level.name}</dt>
			<dd class="text-2xl font-semibold">
				{profile.level.loaded ? levelLabel(profile.level.name, profile.level.estimate) : '–'}
			</dd>
			<dd class="text-xs text-muted">
				{profile.level.loaded ? 'hardest level with 80% known' : 'lists not loaded'}
			</dd>
		</div>
		<div class="rounded-xl border border-line bg-surface p-4">
			<dt class="text-muted">Marked by you</dt>
			<dd class="text-2xl font-semibold">{profile.marked.known + profile.marked.unknown}</dd>
			<dd class="text-xs text-muted">
				{profile.marked.known} known, {profile.marked.unknown} unknown
			</dd>
		</div>
	</dl>

	{#if profile.level.loaded}
		<section class="mt-8">
			<h2 class="text-sm font-semibold">{profile.level.name} lists</h2>
			<p class="mt-1 text-sm text-muted">
				Expected share known, over the words each list has that this catalog has seen.
			</p>
			<ul class="mt-3 grid gap-2 sm:grid-cols-4">
				{#each [...profile.level.levels].reverse() as level (level.level)}
					<li class="rounded-lg border border-line bg-surface p-3 text-sm">
						<p class="font-medium">{levelName(profile.level.name, level.level)}</p>
						<p class="text-lg font-semibold">{percent(level.share)}</p>
						<p class="text-xs text-muted">{level.checked} of {level.total} words</p>
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	<section class="mt-8">
		<div class="flex flex-wrap items-baseline justify-between gap-2">
			<h2 class="text-sm font-semibold">Strength by domain</h2>
			<a href="/test/" class="text-sm text-accent hover:underline">Retest or quick check</a>
		</div>
		<p class="mt-1 text-sm text-muted">
			Share of each domain's 500 commonest words you are expected to know, with a range. A long line
			means the test has not asked much about that domain yet.
		</p>
		<div class="mt-3 rounded-xl border border-line bg-surface p-4">
			<DomainChart domains={profile.domains} />
		</div>
		{#if profile.weakest_domain}
			<p class="mt-2 text-sm text-muted">
				Your weakest tested domain is <strong class="text-ink"
					>{nameOf(profile.weakest_domain)}</strong
				>. A fifth of the recommendations are comfortable novels heavy in it.
			</p>
		{/if}
	</section>

	{#if profile.feedback.length}
		<section class="mt-8">
			<h2 class="text-sm font-semibold">How novels felt</h2>
			<p class="mt-1 text-sm text-muted">
				Your feedback beside the coverage predicted at the time. It shows whether the model runs hot
				or cold.
			</p>
			<ul class="mt-3 grid gap-2">
				{#each profile.feedback as f (f.id)}
					<li class="rounded-lg border border-line bg-surface px-3 py-2 text-sm">
						<span class="font-medium">{f.title ?? f.novel}</span>
						<span class="text-muted">
							· {FELT[f.felt]}{#if f.predicted !== null}
								· predicted {percent(f.predicted, 1)}{/if} · {when(f.at)}</span
						>
						{#if f.note}<p class="mt-1 text-muted">{f.note}</p>{/if}
					</li>
				{/each}
			</ul>
		</section>
	{/if}
{/if}

<section class="mt-8">
	<h2 class="text-sm font-semibold">Words</h2>
	<p class="mt-1 text-sm text-muted">
		Mark a word known or unknown to correct the model, or fix which domains it belongs to. Your
		fixes are kept in your profile and survive a catalog rebuild.
	</p>
	<div class="mt-3 grid gap-3 rounded-xl border border-line bg-surface p-4 sm:grid-cols-3">
		<label class="text-sm sm:col-span-3">
			<span class="text-muted">Search a word or {L.code === 'zh' ? 'pinyin' : 'reading'}</span>
			<input
				type="search"
				bind:value={q}
				oninput={() => (offset = 0)}
				class="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2"
				lang={L.htmlLang}
			/>
		</label>
		<label class="text-sm">
			<span class="text-muted">Show</span>
			<select
				bind:value={status}
				onchange={() => (offset = 0)}
				class="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2"
			>
				<option value="any">All words</option>
				<option value="marked">Marked by me</option>
				<option value="known">Marked known</option>
				<option value="unknown">Marked unknown</option>
			</select>
		</label>
		<label class="text-sm sm:col-span-2">
			<span class="text-muted">Domain</span>
			<select
				bind:value={domain}
				onchange={() => (offset = 0)}
				class="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2"
			>
				<option value="">Any domain</option>
				{#each domains as d (d.key)}
					<option value={d.key}>{d.name_en}</option>
				{/each}
			</select>
		</label>
	</div>

	{#if words}
		{#if words.items.length === 0}
			<p class="mt-4 text-sm text-muted">No words match.</p>
		{:else}
			<p class="mt-3 text-sm text-muted">
				{words.total.toLocaleString('en')} words, commonest first
			</p>
			<ul class="mt-2 grid gap-2">
				{#each words.items as word (word.lemma_id)}
					<li class="rounded-lg border border-line bg-surface px-3 py-2 text-sm">
						<div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
							<span>
								<span class="text-base font-medium" lang={L.htmlLang}>{word.lemma}</span>
								{#if word.reading && word.reading !== word.lemma}
									<span class="text-muted" lang={L.htmlLang}> {word.reading}</span>
								{/if}
								<span class="text-muted"> · {word.gloss ?? 'no gloss'}</span>
							</span>
							<span class="text-xs text-muted">
								#{word.rank} · {word.marked === null
									? `${percent(word.p)} likely known`
									: word.marked
										? 'marked known'
										: 'marked unknown'}
							</span>
						</div>
						<div class="mt-2 flex flex-wrap items-center gap-2">
							<button
								type="button"
								aria-pressed={word.marked === true}
								class="rounded-lg border border-line px-2.5 py-1 text-xs font-medium aria-pressed:border-good aria-pressed:text-good"
								onclick={() => mark(word, word.marked === true ? null : true)}>I know it</button
							>
							<button
								type="button"
								aria-pressed={word.marked === false}
								class="rounded-lg border border-line px-2.5 py-1 text-xs font-medium aria-pressed:border-bad aria-pressed:text-bad"
								onclick={() => mark(word, word.marked === false ? null : false)}>I don't</button
							>
							{#each word.domains as d (d.domain)}
								<span class="rounded-full border border-line px-2 py-0.5 text-xs text-muted">
									{nameOf(d.domain)}
								</span>
							{/each}
							<button
								type="button"
								class="text-xs text-accent underline"
								onclick={() => (editing = editing === word.lemma_id ? null : word.lemma_id)}
							>
								Fix domains
							</button>
						</div>
						{#if editing === word.lemma_id}
							<ul class="mt-2 flex flex-wrap gap-2">
								{#each domains as d (d.key)}
									{@const has = word.domains.some((x) => x.domain === d.key)}
									<li>
										<button
											type="button"
											aria-pressed={has}
											class="rounded-full border border-line px-2.5 py-0.5 text-xs aria-pressed:border-accent aria-pressed:text-accent"
											onclick={() => fix(word, d.key, has ? 'remove' : 'add')}
										>
											{d.name_en}
										</button>
									</li>
								{/each}
							</ul>
						{/if}
					</li>
				{/each}
			</ul>
			<nav class="mt-4 flex items-center justify-between" aria-label="Pages">
				<button
					type="button"
					class="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium disabled:opacity-40"
					disabled={offset === 0}
					onclick={() => (offset = Math.max(0, offset - PAGE))}>Previous</button
				>
				<button
					type="button"
					class="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium disabled:opacity-40"
					disabled={offset + PAGE >= words.total}
					onclick={() => (offset += PAGE)}>Next</button
				>
			</nav>
		{/if}
	{/if}
</section>

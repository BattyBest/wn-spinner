<script lang="ts">
	import { onMount } from 'svelte';
	import DomainChart from '#lib/DomainChart.svelte';
	import {
		answerTest,
		getProfile,
		getTestStatus,
		getTestStep,
		startTest,
		type Profile,
		type TestAnswer,
		type TestItem,
		type TestProgress,
		type TestStatus
	} from '#lib/api';
	import { levelLabel } from '#lib/format';
	import { current } from '#lib/lang';

	const L = current();

	type Mode = 'loading' | 'start' | 'running' | 'result' | 'error';
	const RATINGS = [
		{ value: 'almost_all', label: 'Almost all of it' },
		{ value: 'most', label: 'Most of it' },
		{ value: 'gist', label: 'The gist' },
		{ value: 'lost', label: 'I was lost' }
	] as const;

	let mode = $state<Mode>('loading');
	let status = $state<TestStatus | null>(null);
	let session = $state(0);
	let item = $state<TestItem | null>(null);
	let progress = $state<TestProgress | null>(null);
	let profile = $state<Profile | null>(null);
	let message = $state('');
	let busy = $state(false);

	// Per-item state
	let showReading = $state(false);
	let tapped = $state<Set<number>>(new Set());
	let rating = $state<TestAnswer['rating']>(undefined);
	let clozeChoice = $state<number | null>(null);

	onMount(async () => {
		try {
			status = await getTestStatus();
			mode = 'start';
		} catch {
			message = "Can't reach the API. Start it with `make run`.";
			mode = 'error';
		}
	});

	function show(step: { item: TestItem | null; progress: TestProgress; done: boolean }) {
		progress = step.progress;
		showReading = false;
		tapped = new Set();
		rating = undefined;
		clozeChoice = null;
		if (step.done) {
			finish();
		} else {
			item = step.item;
			mode = 'running';
		}
	}

	async function finish() {
		item = null;
		try {
			profile = await getProfile();
			mode = 'result';
		} catch {
			message = 'The test is finished, but the result could not be loaded.';
			mode = 'error';
		}
	}

	async function begin(kind: 'full' | 'quick') {
		busy = true;
		try {
			const step = await startTest(kind);
			session = step.session;
			show(step);
		} catch (error) {
			message = String(error);
			mode = 'error';
		} finally {
			busy = false;
		}
	}

	async function submit(answer: TestAnswer) {
		if (busy) return;
		busy = true;
		try {
			show(await answerTest(session, answer));
		} catch (error) {
			message = String(error);
			mode = 'error';
		} finally {
			busy = false;
		}
	}

	async function resume() {
		if (!status?.unfinished) return;
		busy = true;
		try {
			session = status.unfinished.id;
			show(await getTestStep(session));
		} catch (error) {
			message = String(error);
			mode = 'error';
		} finally {
			busy = false;
		}
	}

	function toggle(index: number) {
		const next = new Set(tapped);
		if (next.has(index)) next.delete(index);
		else next.add(index);
		tapped = next;
	}

	function onkey(event: KeyboardEvent) {
		if (mode !== 'running' || !item || event.ctrlKey || event.metaKey || event.altKey) return;
		const target = event.target as HTMLElement;
		if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
		const key = event.key.toLowerCase();
		if (item.type === 'word' || item.type === 'fake') {
			if (key === 'k') submit({ known: true });
			else if (key === 'j') submit({ known: false });
			else if (key === 'r' && item.type === 'word') showReading = !showReading;
		} else if (item.type === 'meaning') {
			const n = Number(key);
			if (n >= 1 && n <= item.choices.length) submit({ choice: n - 1 });
			else if (key === '0') submit({ choice: null });
		}
	}

	const total = $derived(progress ? progress.words_total + progress.passages_total : 0);
	const done = $derived(progress ? progress.words_done + progress.passages_done : 0);
	const partLabel = $derived(
		progress?.part === 'B'
			? `Passage ${Math.min(progress.passages_done + 1, progress.passages_total)} of ${progress.passages_total}`
			: progress
				? `Word ${Math.min(progress.words_done + 1, progress.words_total)} of ${progress.words_total}`
				: ''
	);
</script>

<svelte:head><title>Placement test · wn-spinner</title></svelte:head>
<svelte:window onkeydown={onkey} />

<h1 class="text-2xl font-semibold tracking-tight">Placement test</h1>

{#if mode === 'loading'}
	<p class="mt-3 text-sm text-muted">Loading…</p>
{:else if mode === 'error'}
	<p class="mt-4 rounded-xl border border-line bg-surface p-5 text-sm text-bad">{message}</p>
	<button type="button" class="mt-3 text-sm text-accent underline" onclick={() => location.reload()}
		>Reload</button
	>
{:else if mode === 'start' && status}
	<p class="mt-2 text-muted">
		About 10 minutes. First a word check, then a few short passages. Your answers are saved as you
		go, so you can stop and carry on later.
	</p>
	{#if !status.ready}
		<div class="mt-6 rounded-xl border border-dashed border-line bg-surface p-5">
			<p class="text-sm font-medium">Not ready yet</p>
			{#each status.problems as problem (problem)}
				<p class="mt-1 text-sm text-muted">{problem}</p>
			{/each}
		</div>
	{:else}
		<ul class="mt-5 list-disc space-y-1 pl-5 text-sm text-muted">
			<li>Answer "I know it" only for words whose meaning you could give.</li>
			<li>
				Some words are made up. Saying you know one makes your other answers count for less, so
				guessing doesn't help.
			</li>
			<li>
				Keys: K for "I know it", J for "I don't", R to show the {L.code === 'zh'
					? 'pinyin'
					: 'reading'}.
			</li>
		</ul>
		<div class="mt-6 flex flex-wrap gap-3">
			{#if status.unfinished}
				<button
					type="button"
					disabled={busy}
					class="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-accent-ink disabled:opacity-50"
					onclick={resume}
				>
					Continue where you left off
				</button>
			{:else}
				<button
					type="button"
					disabled={busy}
					class="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-accent-ink disabled:opacity-50"
					onclick={() => begin('full')}
				>
					{status.answers ? 'Retake the full test' : 'Start the test'}
				</button>
				{#if status.answers}
					<button
						type="button"
						disabled={busy}
						class="rounded-lg border border-line bg-surface px-4 py-2.5 text-sm font-medium disabled:opacity-50"
						onclick={() => begin('quick')}
					>
						Quick check (20 words)
					</button>
				{/if}
			{/if}
		</div>
		{#if status.excerpts === 0}
			<p class="mt-4 text-sm text-muted">
				No passages are saved yet, so only the word check will run. Run
				<code class="font-mono">uv run wn {L.command} excerpts</code> to add them.
			</p>
		{/if}
	{/if}
{:else if mode === 'running' && item && progress}
	<div class="mt-4">
		<div class="flex items-baseline justify-between text-xs text-muted">
			<span>{partLabel}</span>
			<span>{progress.kind === 'quick' ? 'Quick check' : 'Full test'}</span>
		</div>
		<div
			class="mt-1 h-1.5 overflow-hidden rounded-full bg-line"
			role="progressbar"
			aria-label="Test progress"
			aria-valuemin="0"
			aria-valuemax={total}
			aria-valuenow={done}
		>
			<div class="h-full bg-accent" style:width={`${total ? (done / total) * 100 : 0}%`}></div>
		</div>
	</div>

	{#if item.type === 'word' || item.type === 'fake'}
		{@const word = item.type === 'word' ? item.lemma : item.text}
		<section class="mt-6 rounded-xl border border-line bg-surface p-6 text-center">
			<p class="text-sm text-muted">Do you know this word?</p>
			<p class="mt-4 text-5xl font-semibold tracking-wide" lang={L.htmlLang}>{word}</p>
			<p class="mt-3 min-h-6 text-lg text-muted" lang={L.htmlLang}>
				{#if item.type === 'word' && showReading}{item.reading ?? ''}{/if}
			</p>
			{#if item.type === 'word'}
				<button
					type="button"
					class="mt-1 text-xs text-accent underline"
					onclick={() => (showReading = !showReading)}
				>
					{showReading ? 'Hide' : 'Show'}
					{L.code === 'zh' ? 'pinyin' : 'reading'}{showReading ? '' : ' (R)'}
				</button>
			{/if}
			<div class="mt-6 grid grid-cols-2 gap-3">
				<button
					type="button"
					disabled={busy}
					class="rounded-lg border border-line bg-bg px-4 py-4 text-base font-medium disabled:opacity-50"
					onclick={() => submit({ known: false })}
				>
					I don't <span class="text-xs text-muted">(J)</span>
				</button>
				<button
					type="button"
					disabled={busy}
					class="rounded-lg bg-accent px-4 py-4 text-base font-semibold text-accent-ink disabled:opacity-50"
					onclick={() => submit({ known: true })}
				>
					I know it <span class="text-xs opacity-80">(K)</span>
				</button>
			</div>
		</section>
	{:else if item.type === 'meaning'}
		<section class="mt-6 rounded-xl border border-line bg-surface p-6">
			<p class="text-sm text-muted">Which meaning fits this word?</p>
			<p class="mt-3 text-center text-4xl font-semibold" lang={L.htmlLang}>{item.lemma}</p>
			<p class="mt-1 text-center text-muted" lang={L.htmlLang}>{item.reading ?? ''}</p>
			<ul class="mt-5 grid gap-2">
				{#each item.choices as choice, i (i)}
					<li>
						<button
							type="button"
							disabled={busy}
							class="w-full rounded-lg border border-line bg-bg px-4 py-3 text-left text-sm disabled:opacity-50"
							onclick={() => submit({ choice: i })}
						>
							<span class="mr-2 text-xs text-muted">{i + 1}</span>{choice}
						</button>
					</li>
				{/each}
				<li>
					<button
						type="button"
						disabled={busy}
						class="w-full rounded-lg px-4 py-2 text-left text-sm text-muted underline disabled:opacity-50"
						onclick={() => submit({ choice: null })}
					>
						I'm not sure (0)
					</button>
				</li>
			</ul>
		</section>
	{:else if item.type === 'passage'}
		{@const cloze = item.cloze}
		<section class="mt-6 rounded-xl border border-line bg-surface p-6">
			<p class="text-sm text-muted">
				Tap every word you don't know. Then say how much you understood.
			</p>
			<p class="mt-4 text-lg leading-loose" lang={L.htmlLang}>
				{#each item.tokens as [surface, tappable], i (i)}
					{#if cloze && cloze.index === i}
						<span class="mx-0.5 rounded bg-line px-2 py-0.5 text-muted">＿＿＿</span>
					{:else if tappable}
						<button
							type="button"
							aria-pressed={tapped.has(i)}
							class="rounded px-0.5 hover:bg-bg aria-pressed:bg-bad aria-pressed:text-accent-ink"
							onclick={() => toggle(i)}>{surface}</button
						>
					{:else}
						<span>{surface}</span>
					{/if}
				{/each}
			</p>
			<fieldset class="mt-6">
				<legend class="text-sm font-medium">How much did you understand?</legend>
				<div class="mt-2 grid gap-2 sm:grid-cols-2">
					{#each RATINGS as r (r.value)}
						<label
							class="flex items-center gap-2 rounded-lg border border-line bg-bg px-3 py-2 text-sm has-[:checked]:border-accent"
						>
							<input type="radio" name="rating" value={r.value} bind:group={rating} />
							{r.label}
						</label>
					{/each}
				</div>
			</fieldset>
			{#if cloze}
				<fieldset class="mt-6">
					<legend class="text-sm font-medium">Which word fits the blank?</legend>
					<div class="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
						{#each cloze.choices as choice, i (i)}
							<label
								class="flex items-center justify-center rounded-lg border border-line bg-bg px-3 py-2 text-sm has-[:checked]:border-accent"
								lang={L.htmlLang}
							>
								<input
									type="radio"
									name="cloze"
									class="sr-only"
									value={i}
									bind:group={clozeChoice}
								/>
								{choice}
							</label>
						{/each}
					</div>
					<button
						type="button"
						class="mt-2 text-xs text-muted underline"
						onclick={() => (clozeChoice = null)}>Skip this question</button
					>
				</fieldset>
			{/if}
			<button
				type="button"
				disabled={busy || !rating}
				class="mt-6 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-accent-ink disabled:opacity-50"
				onclick={() =>
					submit({ tapped: [...tapped], rating, cloze_choice: cloze ? clozeChoice : null })}
			>
				Next
			</button>
		</section>
	{/if}
	<p class="mt-4 text-xs text-muted">
		You can close this page at any time. Come back to Test and choose "Continue".
	</p>
{:else if mode === 'result' && profile}
	<p class="mt-2 text-muted">Here is where you stand. It sharpens with every answer.</p>
	<dl class="mt-5 grid grid-cols-2 gap-3 text-sm">
		<div class="rounded-xl border border-line bg-surface p-4">
			<dt class="text-muted">Vocabulary</dt>
			<dd class="text-2xl font-semibold">about {profile.vocabulary.toLocaleString('en')}</dd>
			<dd class="text-xs text-muted">
				likely {profile.vocabulary_range[0].toLocaleString('en')} to {profile.vocabulary_range[1].toLocaleString(
					'en'
				)} words in this catalog's ranking
			</dd>
		</div>
		<div class="rounded-xl border border-line bg-surface p-4">
			<dt class="text-muted">{profile.level.name}</dt>
			<dd class="text-2xl font-semibold">
				{profile.level.loaded
					? levelLabel(profile.level.name, profile.level.estimate)
					: 'not loaded'}
			</dd>
			<dd class="text-xs text-muted">
				{#if profile.level.loaded}
					the hardest level where you know at least 80%
				{:else}
					run <code class="font-mono">wn dict fetch --lang {L.code}</code> to add the {profile.level
						.name} lists
				{/if}
			</dd>
		</div>
	</dl>
	<section class="mt-8">
		<h2 class="text-sm font-semibold">Strength by domain</h2>
		<p class="mt-1 text-sm text-muted">
			Share of each domain's 500 commonest words you are expected to know. The line shows the range.
		</p>
		<div class="mt-3 rounded-xl border border-line bg-surface p-4">
			<DomainChart domains={profile.domains} />
		</div>
	</section>
	<div class="mt-8 flex flex-wrap gap-3">
		<a
			href="/?sort=best"
			class="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-accent-ink"
		>
			See novels for you
		</a>
		<a
			href="/profile/"
			class="rounded-lg border border-line bg-surface px-4 py-2.5 text-sm font-medium"
		>
			Open my profile
		</a>
	</div>
{/if}

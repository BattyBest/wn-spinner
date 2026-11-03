<script lang="ts">
	import { onMount } from 'svelte';
	import Placeholder from '#lib/Placeholder.svelte';
	import { getHealth, getStats, type Health, type Stats } from '#lib/api';

	let health = $state<Health | null>(null);
	let stats = $state<Stats | null>(null);
	let failed = $state(false);

	onMount(async () => {
		try {
			[health, stats] = await Promise.all([getHealth(), getStats()]);
		} catch {
			failed = true;
		}
	});
</script>

<Placeholder
	title="Discover"
	summary="Novels matched to your level, with the share of words you should already know."
	arrives="milestone 2 (Japanese) and milestone 4 (Chinese)"
>
	<section class="mt-6 rounded-xl border border-line bg-surface p-5" aria-live="polite">
		<h2 class="text-sm font-semibold">Local service</h2>
		{#if failed}
			<p class="mt-1 text-sm text-bad">
				Can't reach the API. Start it with <code class="font-mono">make run</code>.
			</p>
		{:else if health && stats}
			<p class="mt-1 text-sm text-good">Connected · version {health.version}</p>
			<dl class="mt-3 grid grid-cols-3 gap-3 text-sm">
				<div>
					<dt class="text-muted">Novels</dt>
					<dd class="text-lg font-semibold">{stats.novels}</dd>
				</div>
				<div>
					<dt class="text-muted">Cached pages</dt>
					<dd class="text-lg font-semibold">{stats.cache_pages}</dd>
				</div>
				<div>
					<dt class="text-muted">Sources</dt>
					<dd class="text-lg font-semibold">{stats.sources.map((s) => s.name).join(', ')}</dd>
				</div>
			</dl>
		{:else}
			<p class="mt-1 text-sm text-muted">Checking…</p>
		{/if}
	</section>
</Placeholder>

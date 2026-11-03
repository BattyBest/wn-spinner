<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		title,
		summary,
		arrives,
		children
	}: { title: string; summary: string; arrives: string; children?: Snippet } = $props();
</script>

<svelte:head><title>{title} · wn-spinner</title></svelte:head>

<h1 class="text-2xl font-semibold tracking-tight">{title}</h1>
<p class="mt-2 text-muted">{summary}</p>

<div class="mt-6 rounded-xl border border-dashed border-line bg-surface p-5">
	<p class="text-sm font-medium">Coming in {arrives}</p>
	<p class="mt-1 text-sm text-muted">
		This screen is a placeholder so navigation works end to end.
	</p>
</div>

{@render children?.()}

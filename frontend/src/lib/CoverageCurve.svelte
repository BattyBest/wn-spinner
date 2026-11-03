<script lang="ts">
	import { percent } from '#lib/format';

	let { points }: { points: { words: number; cover: number }[] } = $props();

	const width = 400;
	const height = 220;
	const pad = { left: 42, right: 14, top: 12, bottom: 30 };
	const maxWords = $derived(Math.max(...points.map((p) => p.words), 1));
	const x = (words: number) => pad.left + (words / maxWords) * (width - pad.left - pad.right);
	const y = (cover: number) => pad.top + (1 - cover) * (height - pad.top - pad.bottom);
	const path = $derived(
		points.map((p, i) => `${i ? 'L' : 'M'}${x(p.words)} ${y(p.cover)}`).join(' ')
	);
	const grid = [0, 0.25, 0.5, 0.75, 1];
	const label = (words: number) => (words === 0 ? '0' : `${words / 1000}k`);
</script>

<figure>
	<svg
		viewBox="0 0 {width} {height}"
		class="w-full"
		role="img"
		aria-label="Share of the text covered when you know the most common N words"
	>
		{#each grid as g (g)}
			<line x1={pad.left} x2={width - pad.right} y1={y(g)} y2={y(g)} class="stroke-line" />
			<text x={pad.left - 8} y={y(g) + 4} text-anchor="end" class="fill-muted text-[12px]">
				{Math.round(g * 100)}%
			</text>
		{/each}
		<path d={path} fill="none" class="stroke-accent" stroke-width="2.5" stroke-linejoin="round" />
		{#each points as p (p.words)}
			<circle cx={x(p.words)} cy={y(p.cover)} r="3.5" class="fill-accent" />
			<text x={x(p.words)} y={height - 10} text-anchor="middle" class="fill-muted text-[12px]">
				{label(p.words)}
			</text>
		{/each}
	</svg>
	<figcaption class="mt-1 text-xs text-muted">
		Words you know, most common first (horizontal) against the share of this sample they cover
		(vertical).
	</figcaption>
</figure>
<details class="mt-2 text-xs text-muted">
	<summary class="cursor-pointer">Show the numbers</summary>
	<table class="mt-2 w-full max-w-xs text-left">
		<thead>
			<tr><th class="font-medium">Top words</th><th class="font-medium">Covers</th></tr>
		</thead>
		<tbody>
			{#each points.filter((p) => p.words > 0) as p (p.words)}
				<tr><td>{p.words.toLocaleString('en')}</td><td>{percent(p.cover, 1)}</td></tr>
			{/each}
		</tbody>
	</table>
</details>

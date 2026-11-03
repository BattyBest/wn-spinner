<script lang="ts">
	import type { DomainStrength } from '#lib/api';
	import { percent } from '#lib/format';

	let { domains }: { domains: DomainStrength[] } = $props();

	// Bars show the share of each domain's 500 commonest words you are expected to know,
	// with a whisker for one standard deviation of that domain's own offset. The name sits
	// above its bar so long names fit on a phone.
	const tested = $derived(
		[...domains].filter((d) => d.share !== null).sort((a, b) => b.share! - a.share!)
	);
	const untested = $derived(domains.filter((d) => d.share === null));
	const ROW = 46;
	const LEFT = 4;
	const WIDTH = 400;
	const x = (v: number) => LEFT + v * (WIDTH - LEFT - 44);
</script>

{#if tested.length}
	<svg
		viewBox="0 0 {WIDTH} {tested.length * ROW + 22}"
		class="w-full"
		role="img"
		aria-label="Share of each domain's common words you are expected to know"
	>
		{#each [0, 0.25, 0.5, 0.75, 1] as tick (tick)}
			<line x1={x(tick)} x2={x(tick)} y1="0" y2={tested.length * ROW} stroke="var(--border)" />
			<text
				x={x(tick)}
				y={tested.length * ROW + 16}
				text-anchor={tick === 0 ? 'start' : tick === 1 ? 'end' : 'middle'}
				font-size="11"
				fill="var(--muted)">{tick * 100}%</text
			>
		{/each}
		{#each tested as d, i (d.key)}
			{@const y = i * ROW}
			<text x={LEFT} y={y + 15} font-size="13" fill="var(--text)">{d.name_en}</text>
			<rect
				x={x(0)}
				y={y + 22}
				width={x(d.share!) - x(0)}
				height="14"
				rx="3"
				fill="var(--accent)"
			/>
			<line
				x1={x(d.low!)}
				x2={x(d.high!)}
				y1={y + 29}
				y2={y + 29}
				stroke="var(--text)"
				stroke-width="1.5"
			/>
			<line x1={x(d.low!)} x2={x(d.low!)} y1={y + 24} y2={y + 34} stroke="var(--text)" />
			<line x1={x(d.high!)} x2={x(d.high!)} y1={y + 24} y2={y + 34} stroke="var(--text)" />
			<text x={x(d.high!) + 6} y={y + 33} font-size="12" fill="var(--text)">{percent(d.share)}</text
			>
		{/each}
	</svg>
{/if}
{#if untested.length}
	<p class="mt-2 text-xs text-muted">
		Not enough words to show: {untested.map((d) => d.name_en).join(', ')}. Run
		<code class="font-mono">uv run wn analyse --domains</code> after collecting more novels.
	</p>
{/if}

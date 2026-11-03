<script lang="ts">
	import { percent } from '#lib/format';

	let { value, label }: { value: number; label: string } = $props();
</script>

<div>
	<div class="flex items-baseline justify-between text-xs text-muted">
		<span>{label}</span>
		<span class="font-medium text-ink">{percent(value)}</span>
	</div>
	<div
		class="mt-1 h-2 overflow-hidden rounded-full bg-line"
		role="meter"
		aria-label={label}
		aria-valuemin="0"
		aria-valuemax="100"
		aria-valuenow={Math.round(value * 100)}
	>
		<div class="h-full rounded-full bg-accent" style:width={`${Math.round(value * 100)}%`}></div>
	</div>
</div>

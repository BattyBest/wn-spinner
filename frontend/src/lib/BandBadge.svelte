<script lang="ts">
	import type { Band } from '#lib/api';
	import { BAND_LABEL, percent } from '#lib/format';

	let { band, coverage }: { band: Band; coverage: number } = $props();

	// Colour is never the only signal: the label and the percentage are always written out.
	const tone = {
		comfortable: 'border-good text-good',
		stretch: 'border-accent text-accent',
		hard: 'border-line text-ink',
		too_hard: 'border-bad text-bad'
	};
</script>

<span
	class="inline-flex items-baseline gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium {tone[
		band
	]}"
>
	{BAND_LABEL[band]}
	<span class="font-normal text-muted">{percent(coverage, 1)} for you</span>
</span>

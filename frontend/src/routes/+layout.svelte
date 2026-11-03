<script lang="ts">
	import '../app.css';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { screens } from '#lib/nav';
	import { LANGS, getLang, setLang, type LangCode } from '#lib/lang';

	let { children } = $props();

	let lang = $state<LangCode>('ja');
	onMount(() => (lang = getLang()));
	const choose = (code: LangCode) => code !== lang && setLang(code);

	const active = (href: string) =>
		href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
</script>

{#snippet switcher()}
	<div
		class="inline-flex rounded-lg border border-line p-0.5 text-sm"
		role="group"
		aria-label="Language"
	>
		{#each Object.values(LANGS) as option (option.code)}
			<button
				type="button"
				lang={option.htmlLang}
				aria-pressed={lang === option.code}
				class="rounded-md px-3 py-1 font-medium text-muted aria-pressed:bg-accent aria-pressed:text-accent-ink"
				onclick={() => choose(option.code)}
			>
				{option.label}
			</button>
		{/each}
	</div>
{/snippet}

<div class="min-h-screen md:grid md:grid-cols-[14rem_1fr]">
	<aside
		class="hidden border-r border-line bg-surface md:sticky md:top-0 md:flex md:h-screen md:flex-col md:gap-6 md:p-5"
	>
		<a href="/" class="text-lg font-semibold tracking-tight">wn-spinner</a>
		<nav class="flex flex-col gap-1" aria-label="Main">
			{#each screens as screen (screen.href)}
				<a
					href={screen.href}
					aria-current={active(screen.href) ? 'page' : undefined}
					class="rounded-lg px-3 py-2 text-sm font-medium text-muted hover:bg-bg aria-[current=page]:bg-accent aria-[current=page]:text-accent-ink"
				>
					{screen.label}
				</a>
			{/each}
		</nav>
		<div class="mt-auto">{@render switcher()}</div>
	</aside>

	<main class="mx-auto w-full max-w-3xl px-4 pt-6 pb-28 md:px-8 md:pt-10 md:pb-10">
		<div class="mb-4 flex justify-end md:hidden">{@render switcher()}</div>
		{@render children()}
	</main>

	<nav
		class="fixed inset-x-0 bottom-0 z-10 grid grid-cols-5 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] md:hidden"
		aria-label="Main"
	>
		{#each screens as screen (screen.href)}
			<a
				href={screen.href}
				aria-current={active(screen.href) ? 'page' : undefined}
				class="py-3 text-center text-xs font-medium text-muted aria-[current=page]:text-accent"
			>
				{screen.label}
			</a>
		{/each}
	</nav>
</div>

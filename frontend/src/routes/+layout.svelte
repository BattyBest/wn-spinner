<script lang="ts">
	import '../app.css';
	import { page } from '$app/state';
	import { screens } from '#lib/nav';

	let { children } = $props();

	const active = (href: string) =>
		href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
</script>

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
	</aside>

	<main class="mx-auto w-full max-w-3xl px-4 pt-6 pb-28 md:px-8 md:pt-10 md:pb-10">
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

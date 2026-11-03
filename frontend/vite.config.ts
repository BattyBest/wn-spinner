import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			// The built UI lands inside the Python package, where `wn serve` mounts it.
			adapter: adapter({
				pages: '../src/wn/api/static',
				assets: '../src/wn/api/static',
				precompress: false,
				strict: true
			})
		})
	],
	server: {
		// `make dev` runs the API on :8000; the dev server forwards /api to it.
		proxy: { '/api': 'http://localhost:8000' }
	}
});

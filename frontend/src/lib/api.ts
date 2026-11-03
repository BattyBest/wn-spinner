export type Health = {
	status: string;
	version: string;
	catalog_version: number;
	profile_version: number;
};

export type Stats = {
	novels: number;
	cache_pages: number;
	cache_bytes: number;
	sources: { name: string; language: string; novels: number }[];
};

async function get<T>(path: string): Promise<T> {
	const response = await fetch(path);
	if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
	return (await response.json()) as T;
}

export const getHealth = () => get<Health>('/api/health');
export const getStats = () => get<Stats>('/api/stats');

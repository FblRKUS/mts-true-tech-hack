<script lang="ts">
	import { getContext } from 'svelte';
	import MediaGallery from '$lib/components/gallery/MediaGallery.svelte';
	import { showSidebar } from '$lib/stores';

	const i18n = getContext('i18n') as { t?: (key: string) => string } | undefined;
	const t = (key: string) => i18n?.t?.(key) ?? key;
</script>

<div
	class="flex flex-col w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
		? 'md:max-w-[calc(100%-var(--sidebar-width))]'
		: ''} max-w-full"
>
	<div class="px-3 md:px-[18px] pt-2 pb-2 flex flex-col h-full min-h-0">
		<div class="flex justify-between items-center mb-3">
			<div class="flex md:self-center text-xl font-medium px-0.5">
				{t('Media Gallery')}
			</div>
		</div>

		<div class="flex-1 min-h-0">
			<MediaGallery />
		</div>
	</div>
</div>

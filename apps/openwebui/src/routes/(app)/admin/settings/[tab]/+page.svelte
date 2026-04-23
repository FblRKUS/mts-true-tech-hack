<script>
	import { getContext } from 'svelte';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';
	import Settings from '$lib/components/admin/Settings.svelte';
	import GPTHub from '$lib/components/admin/Settings/GPTHub.svelte';

	const i18n = getContext('i18n');
</script>

{#if $page.params.tab === 'gpthub'}
	<GPTHub
		on:save={() => {
			toast.success($i18n.t('Settings saved successfully!'));
		}}
	/>
{:else}
	<Settings />
{/if}

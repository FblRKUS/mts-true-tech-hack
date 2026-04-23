<script lang="ts">
	import { getContext } from 'svelte';
	import WorkspaceFileTree from '$lib/components/workspace/WorkspaceFileTree.svelte';

	const i18n = getContext('i18n');
</script>

<div class="flex flex-col h-full pt-0.5">
	<div class="flex justify-between items-center mb-3">
		<div class="flex md:self-center text-xl font-medium px-0.5">
			{$i18n.t('Workspace')}
		</div>
	</div>

	<div class="flex-1 min-h-0" style="height: calc(100vh - 120px)">
		<WorkspaceFileTree />
	</div>
</div>

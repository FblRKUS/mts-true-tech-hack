import { c as store_get, e as ensure_array_like, d as attr_class, t as stringify, k as escape_html, a as attr, u as unsubscribe_stores, o as getContext } from "../../../../../chunks/root.js";
import "../../../../../chunks/Toaster.svelte_svelte_type_style_lang.js";
import { u as user } from "../../../../../chunks/index2.js";
import "../../../../../chunks/codemirror.js";
import { M as Markdown } from "../../../../../chunks/Markdown.js";
function WorkspaceFileTree($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    var $$store_subs;
    let workspaces = [];
    let activeWorkspace = null;
    let nodes = [];
    let aiMessages = [];
    let aiInput = "";
    store_get($$store_subs ??= {}, "$user", user)?.id ?? "";
    nodes.filter((n) => n.parent_id === null).sort((a, b) => {
      if (a.node_type !== b.node_type) return a.node_type === "directory" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    $$renderer2.push(`<div class="flex h-full min-h-0 gap-0 overflow-hidden rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900">`);
    {
      $$renderer2.push("<!--[0-->");
      $$renderer2.push(`<div class="flex w-56 shrink-0 flex-col border-r border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-900"><div class="flex items-center justify-between px-3 py-2 border-b border-gray-100 dark:border-gray-800"><span class="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Workspaces</span> <button class="rounded p-0.5 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400" title="New workspace"><svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"></path></svg></button></div> `);
      {
        $$renderer2.push("<!--[-1-->");
      }
      $$renderer2.push(`<!--]--> <div class="flex-1 overflow-y-auto py-1"><!--[-->`);
      const each_array = ensure_array_like(workspaces);
      for (let $$index = 0, $$length = each_array.length; $$index < $$length; $$index++) {
        let ws = each_array[$$index];
        $$renderer2.push(`<div${attr_class(`group flex items-center justify-between rounded mx-1 px-2 py-1.5 cursor-pointer text-sm ${stringify(activeWorkspace?.id === ws.id ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 font-medium" : "text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800")}`)} role="button" tabindex="0"><span class="truncate text-xs">${escape_html(ws.name)}</span> <button class="invisible group-hover:visible ml-1 rounded p-0.5 text-gray-400 hover:text-red-500" title="Delete workspace"><svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"></path></svg></button></div>`);
      }
      $$renderer2.push(`<!--]--> `);
      if (workspaces.length === 0) {
        $$renderer2.push("<!--[0-->");
        $$renderer2.push(`<p class="px-3 py-4 text-xs text-center text-gray-400 dark:text-gray-500">No workspaces yet</p>`);
      } else {
        $$renderer2.push("<!--[-1-->");
      }
      $$renderer2.push(`<!--]--></div></div>`);
    }
    $$renderer2.push(`<!--]--> <div class="flex w-64 shrink-0 flex-col border-r border-gray-100 dark:border-gray-800">`);
    {
      $$renderer2.push("<!--[-1-->");
      $$renderer2.push(`<div class="flex flex-1 items-center justify-center p-4 text-xs text-gray-400 dark:text-gray-500">Select a workspace</div>`);
    }
    $$renderer2.push(`<!--]--></div> <div class="flex flex-1 flex-col min-w-0"><div class="flex flex-1 min-h-0"><div class="flex flex-1 min-w-0 flex-col border-r border-gray-100 dark:border-gray-800">`);
    {
      $$renderer2.push("<!--[-1-->");
      $$renderer2.push(`<div class="flex flex-1 items-center justify-center text-sm text-gray-400 dark:text-gray-500">Select a file to edit</div>`);
    }
    $$renderer2.push(`<!--]--></div> <div class="flex w-[360px] shrink-0 flex-col"><div class="border-b border-gray-100 dark:border-gray-800 px-3 py-2"><div class="text-xs font-semibold text-gray-600 dark:text-gray-300">Workspace Agent</div></div> <div class="flex-1 overflow-y-auto p-3 space-y-2">`);
    if (aiMessages.length === 0) {
      $$renderer2.push("<!--[0-->");
      $$renderer2.push(`<div class="text-xs text-gray-400 dark:text-gray-500">Напиши задачу агенту по текущему workspace.</div>`);
    } else {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--> <!--[-->`);
    const each_array_2 = ensure_array_like(aiMessages);
    for (let $$index_2 = 0, $$length = each_array_2.length; $$index_2 < $$length; $$index_2++) {
      let message = each_array_2[$$index_2];
      $$renderer2.push(`<div${attr_class(`w-full ${stringify(message.role === "user" ? "text-right" : "")}`)}>`);
      if (message.role === "assistant") {
        $$renderer2.push("<!--[0-->");
        $$renderer2.push(`<div class="inline-block max-w-[95%] rounded-lg bg-gray-100 dark:bg-gray-800 px-2.5 py-2 text-gray-700 dark:text-gray-200 text-xs text-left">`);
        Markdown($$renderer2, {
          id: `workspace-agent-${message.id}`,
          content: message.content,
          done: true
        });
        $$renderer2.push(`<!----></div>`);
      } else {
        $$renderer2.push("<!--[-1-->");
        $$renderer2.push(`<div class="inline-block max-w-[95%] rounded-lg px-2.5 py-2 text-xs whitespace-pre-wrap bg-blue-600 text-white">${escape_html(message.content)}</div>`);
      }
      $$renderer2.push(`<!--]--></div>`);
    }
    $$renderer2.push(`<!--]--> `);
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--></div> <div class="border-t border-gray-100 dark:border-gray-800 p-2.5"><div class="flex items-end gap-2"><textarea class="h-[122px] w-[265px] shrink-0 resize-none overflow-y-auto rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1.5 text-xs text-gray-800 dark:text-gray-100 outline-none" placeholder="Напиши задачу агенту...">`);
    const $$body = escape_html(aiInput);
    if ($$body) {
      $$renderer2.push(`${$$body}`);
    }
    $$renderer2.push(`</textarea> <div class="relative flex items-center gap-1"><button class="rounded border border-gray-300 bg-gray-100 p-1 text-gray-700 hover:bg-gray-200 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:hover:bg-gray-600" title="Agent options"><svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6h.01M12 12h.01M12 18h.01"></path></svg></button> `);
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--> <button class="rounded bg-blue-600 p-2 text-white hover:bg-blue-700 disabled:opacity-50" aria-label="Send message" title="Send"${attr("disabled", !aiInput.trim(), true)}><svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M13 6l6 6-6 6"></path></svg></button></div></div></div></div></div></div></div>`);
    if ($$store_subs) unsubscribe_stores($$store_subs);
  });
}
function _page($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    var $$store_subs;
    const i18n = getContext("i18n");
    $$renderer2.push(`<div class="flex flex-col h-full pt-0.5"><div class="flex justify-between items-center mb-3"><div class="flex md:self-center text-xl font-medium px-0.5">${escape_html(store_get($$store_subs ??= {}, "$i18n", i18n).t("Workspace"))}</div></div> <div class="flex-1 min-h-0" style="height: calc(100vh - 120px)">`);
    WorkspaceFileTree($$renderer2);
    $$renderer2.push(`<!----></div></div>`);
    if ($$store_subs) unsubscribe_stores($$store_subs);
  });
}
export {
  _page as default
};
//# sourceMappingURL=_page.svelte.js.map

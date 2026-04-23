import { o as getContext, a as attr, k as escape_html, e as ensure_array_like, d as attr_class, t as stringify, c as store_get, u as unsubscribe_stores } from "../../../../chunks/root.js";
import "@sveltejs/kit/internal";
import "../../../../chunks/exports.js";
import "../../../../chunks/utils.js";
import "@sveltejs/kit/internal/server";
import "../../../../chunks/state.svelte.js";
import "../../../../chunks/Toaster.svelte_svelte_type_style_lang.js";
import { j as showSidebar } from "../../../../chunks/index2.js";
function MediaGallery($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    let totalPages, canPrev, canNext;
    const i18n = getContext("i18n");
    const t = (key) => i18n?.t?.(key) ?? key;
    let items = [];
    let loading = false;
    let deletingId = "";
    let search = "";
    let kind = "";
    let page = 1;
    let pageSize = 24;
    let total = 0;
    totalPages = Math.max(1, Math.ceil(total / pageSize));
    canPrev = page > 1;
    canNext = page < totalPages;
    $$renderer2.push(`<div class="flex flex-col h-full min-h-0 gap-3"><div class="flex flex-col lg:flex-row lg:items-center gap-2"><input class="w-full lg:max-w-md bg-transparent border rounded-lg px-3 py-2"${attr("placeholder", t("Search prompt or URL"))}${attr("value", search)}/> `);
    $$renderer2.select(
      {
        class: "bg-transparent border rounded-lg px-3 py-2",
        value: kind
      },
      ($$renderer3) => {
        $$renderer3.option({ value: "" }, ($$renderer4) => {
          $$renderer4.push(`${escape_html(t("All types"))}`);
        });
        $$renderer3.option({ value: "upload" }, ($$renderer4) => {
          $$renderer4.push(`upload`);
        });
        $$renderer3.option({ value: "generated" }, ($$renderer4) => {
          $$renderer4.push(`generated`);
        });
      }
    );
    $$renderer2.push(` <button type="button" class="px-3 py-2 rounded-lg bg-black text-white dark:bg-white dark:text-black disabled:opacity-50"${attr("disabled", loading, true)}>${escape_html(t("Refresh"))}</button></div> <div class="flex-1 min-h-0">`);
    if (items.length === 0) {
      $$renderer2.push("<!--[1-->");
      $$renderer2.push(`<div class="text-sm text-gray-500">${escape_html(t("No media found"))}</div>`);
    } else {
      $$renderer2.push("<!--[-1-->");
      $$renderer2.push(`<div data-gallery-grid="" class="h-full grid grid-cols-1 sm:[grid-template-columns:repeat(auto-fit,minmax(22rem,22rem))] sm:justify-center gap-3 overflow-y-auto pr-1 pb-1 items-start"><!--[-->`);
      const each_array = ensure_array_like(items);
      for (let $$index = 0, $$length = each_array.length; $$index < $$length; $$index++) {
        let item = each_array[$$index];
        $$renderer2.push(`<div data-gallery-card="" class="w-full max-w-[22rem] mx-auto border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden flex flex-col"><div class="aspect-[4/3] bg-gray-100 dark:bg-gray-900"><img class="w-full h-full object-cover"${attr("src", item.thumbnail_url || item.media_url)}${attr("alt", item.kind)}/></div> <div class="p-3 space-y-2 text-xs"><div class="flex items-center justify-between"><span class="font-medium">${escape_html(item.kind)}</span> <span class="text-gray-500">${escape_html(new Date(item.created_at).toLocaleString())}</span></div> <div class="text-gray-500 line-clamp-2">${escape_html(item.prompt_text || "-")}</div> <div class="text-gray-500 truncate">${escape_html(item.model_id || "-")}</div> <div class="flex items-center gap-2"><button type="button" class="px-2 py-1 rounded border border-gray-300 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-900">${escape_html(t("Go to chat"))}</button> <button type="button" class="px-2 py-1 rounded border border-red-300 text-red-600 dark:border-red-800 hover:bg-red-50 dark:hover:bg-red-950/20 disabled:opacity-50"${attr("disabled", deletingId === item.id, true)}>${escape_html(t("Delete"))}</button></div></div></div>`);
      }
      $$renderer2.push(`<!--]--></div>`);
    }
    $$renderer2.push(`<!--]--></div> <div class="flex items-center justify-end gap-2 text-xs"><button type="button" class="px-2 py-1 rounded border border-gray-300 dark:border-gray-700 disabled:opacity-50"${attr("disabled", !canPrev || loading, true)}>${escape_html(t("Prev"))}</button> <span>${escape_html(t("Page"))} ${escape_html(page)} / ${escape_html(totalPages)}</span> <button type="button" class="px-2 py-1 rounded border border-gray-300 dark:border-gray-700 disabled:opacity-50"${attr("disabled", !canNext || loading, true)}>${escape_html(t("Next"))}</button></div></div>`);
  });
}
function _page($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    var $$store_subs;
    const i18n = getContext("i18n");
    const t = (key) => i18n?.t?.(key) ?? key;
    $$renderer2.push(`<div${attr_class(`flex flex-col w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out ${stringify(store_get($$store_subs ??= {}, "$showSidebar", showSidebar) ? "md:max-w-[calc(100%-var(--sidebar-width))]" : "")} max-w-full`)}><div class="px-3 md:px-[18px] pt-2 pb-2 flex flex-col h-full min-h-0"><div class="flex justify-between items-center mb-3"><div class="flex md:self-center text-xl font-medium px-0.5">${escape_html(t("Media Gallery"))}</div></div> <div class="flex-1 min-h-0">`);
    MediaGallery($$renderer2);
    $$renderer2.push(`<!----></div></div></div>`);
    if ($$store_subs) unsubscribe_stores($$store_subs);
  });
}
export {
  _page as default
};
//# sourceMappingURL=_page.svelte.js.map

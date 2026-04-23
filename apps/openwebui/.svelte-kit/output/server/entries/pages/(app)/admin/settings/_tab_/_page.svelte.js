import { o as getContext, c as store_get, u as unsubscribe_stores } from "../../../../../../chunks/root.js";
import { p as page } from "../../../../../../chunks/stores.js";
import "../../../../../../chunks/Toaster.svelte_svelte_type_style_lang.js";
import { G as GPTHub, S as Settings } from "../../../../../../chunks/Settings.js";
function _page($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    var $$store_subs;
    getContext("i18n");
    if (store_get($$store_subs ??= {}, "$page", page).params.tab === "gpthub") {
      $$renderer2.push("<!--[0-->");
      GPTHub($$renderer2);
    } else {
      $$renderer2.push("<!--[-1-->");
      Settings($$renderer2);
    }
    $$renderer2.push(`<!--]-->`);
    if ($$store_subs) unsubscribe_stores($$store_subs);
  });
}
export {
  _page as default
};
//# sourceMappingURL=_page.svelte.js.map

import { o as getContext, c as store_get, q as head, u as unsubscribe_stores, k as escape_html } from "../../../../chunks/root.js";
import { W as WEBUI_NAME } from "../../../../chunks/index2.js";
import { p as page } from "../../../../chunks/stores.js";
import "@sveltejs/kit/internal";
import "../../../../chunks/exports.js";
import "../../../../chunks/utils.js";
import "@sveltejs/kit/internal/server";
import "../../../../chunks/state.svelte.js";
import "dompurify";
function _layout($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    var $$store_subs;
    let isWorkspaceFeatureRoute;
    const i18n = getContext("i18n");
    isWorkspaceFeatureRoute = store_get($$store_subs ??= {}, "$page", page).url.pathname === "/workspace" || store_get($$store_subs ??= {}, "$page", page).url.pathname.startsWith("/workspace/files");
    head("q5mosy", $$renderer2, ($$renderer3) => {
      $$renderer3.title(($$renderer4) => {
        $$renderer4.push(`<title>
		${escape_html(isWorkspaceFeatureRoute ? store_get($$store_subs ??= {}, "$i18n", i18n).t("Workspace") : store_get($$store_subs ??= {}, "$i18n", i18n).t("Studio"))} • ${escape_html(store_get($$store_subs ??= {}, "$WEBUI_NAME", WEBUI_NAME))}
	</title>`);
      });
    });
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]-->`);
    if ($$store_subs) unsubscribe_stores($$store_subs);
  });
}
export {
  _layout as default
};
//# sourceMappingURL=_layout.svelte.js.map

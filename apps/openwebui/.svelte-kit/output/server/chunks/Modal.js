import { f as fallback, d as attr_class, j as slot, b as bind_props, t as stringify } from "./root.js";
import { o as onDestroy } from "./index-server.js";
/* empty css                                    */
function Modal($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    let show = fallback($$props["show"], true);
    let size = fallback($$props["size"], "md");
    let containerClassName = fallback($$props["containerClassName"], "p-3");
    let className = fallback($$props["className"], "bg-white/95 dark:bg-gray-900/95 backdrop-blur-sm rounded-4xl");
    const sizeToWidth = (size2) => {
      if (size2 === "full") {
        return "w-full";
      }
      if (size2 === "xs") {
        return "w-[16rem]";
      } else if (size2 === "sm") {
        return "w-[30rem]";
      } else if (size2 === "md") {
        return "w-[42rem]";
      } else if (size2 === "lg") {
        return "w-[56rem]";
      } else if (size2 === "xl") {
        return "w-[70rem]";
      } else if (size2 === "2xl") {
        return "w-[84rem]";
      } else if (size2 === "3xl") {
        return "w-[100rem]";
      } else {
        return "w-[56rem]";
      }
    };
    onDestroy(() => {
      show = false;
    });
    if (show) {
      $$renderer2.push("<!--[0-->");
      $$renderer2.push(`<div aria-modal="true" role="dialog"${attr_class(`modal fixed top-0 right-0 left-0 bottom-0 bg-black/30 dark:bg-black/60 w-full h-screen max-h-[100dvh] ${stringify(containerClassName)} flex justify-center z-9999 overflow-y-auto overscroll-contain`, "svelte-1vr5p4p")} style="scrollbar-gutter: stable;"><div${attr_class(`m-auto max-w-full ${stringify(sizeToWidth(size))} ${stringify(size !== "full" ? "mx-2" : "")} shadow-3xl min-h-fit scrollbar-hidden ${stringify(className)} border border-white dark:border-gray-850`, "svelte-1vr5p4p")}><!--[-->`);
      slot($$renderer2, $$props, "default", {}, null);
      $$renderer2.push(`<!--]--></div></div>`);
    } else {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]-->`);
    bind_props($$props, { show, size, containerClassName, className });
  });
}
export {
  Modal as M
};
//# sourceMappingURL=Modal.js.map

import { a as WEBUI_API_BASE_URL } from "./constants.js";
import { b as getUserPosition } from "./index3.js";
import { f as fallback, d as attr_class, k as escape_html, b as bind_props, t as stringify } from "./root.js";
const getUsers = async (token, query, orderBy, direction, page = 1) => {
  let error = null;
  let res = null;
  const searchParams = new URLSearchParams();
  searchParams.set("page", `${page}`);
  {
    searchParams.set("order_by", orderBy);
  }
  {
    searchParams.set("direction", direction);
  }
  res = await fetch(`${WEBUI_API_BASE_URL}/users/?${searchParams.toString()}`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`
    }
  }).then(async (res2) => {
    if (!res2.ok) throw await res2.json();
    return res2.json();
  }).catch((err) => {
    error = err.detail;
    return null;
  });
  if (error) {
    throw error;
  }
  return res;
};
const searchUsers = async (token, query, orderBy, direction, page = 1) => {
  let error = null;
  let res = null;
  const searchParams = new URLSearchParams();
  searchParams.set("page", `${page}`);
  {
    searchParams.set("order_by", orderBy);
  }
  {
    searchParams.set("direction", direction);
  }
  res = await fetch(`${WEBUI_API_BASE_URL}/users/search?${searchParams.toString()}`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`
    }
  }).then(async (res2) => {
    if (!res2.ok) throw await res2.json();
    return res2.json();
  }).catch((err) => {
    error = err.detail;
    return null;
  });
  if (error) {
    throw error;
  }
  return res;
};
const getUserSettings = async (token) => {
  let error = null;
  const res = await fetch(`${WEBUI_API_BASE_URL}/users/user/settings`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`
    }
  }).then(async (res2) => {
    if (!res2.ok) throw await res2.json();
    return res2.json();
  }).catch((err) => {
    error = err.detail;
    return null;
  });
  if (error) {
    throw error;
  }
  return res;
};
const updateUserSettings = async (token, settings) => {
  let error = null;
  const res = await fetch(`${WEBUI_API_BASE_URL}/users/user/settings/update`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`
    },
    body: JSON.stringify({
      ...settings
    })
  }).then(async (res2) => {
    if (!res2.ok) throw await res2.json();
    return res2.json();
  }).catch((err) => {
    error = err.detail;
    return null;
  });
  if (error) {
    throw error;
  }
  return res;
};
const getUserInfoById = async (token, userId) => {
  let error = null;
  const res = await fetch(`${WEBUI_API_BASE_URL}/users/${userId}/info`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`
    }
  }).then(async (res2) => {
    if (!res2.ok) throw await res2.json();
    return res2.json();
  }).catch((err) => {
    error = err.detail;
    return null;
  });
  if (error) {
    throw error;
  }
  return res;
};
const updateUserInfo = async (token, info) => {
  let error = null;
  const res = await fetch(`${WEBUI_API_BASE_URL}/users/user/info/update`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`
    },
    body: JSON.stringify({
      ...info
    })
  }).then(async (res2) => {
    if (!res2.ok) throw await res2.json();
    return res2.json();
  }).catch((err) => {
    error = err.detail;
    return null;
  });
  if (error) {
    throw error;
  }
  return res;
};
const getAndUpdateUserLocation = async (token) => {
  const location = await getUserPosition().catch((err) => {
    return null;
  });
  if (location) {
    await updateUserInfo(token, { location });
    return location;
  } else {
    console.info("Failed to get user location");
    return null;
  }
};
const getUserGroupsById = async (token, userId) => {
  let error = null;
  const res = await fetch(`${WEBUI_API_BASE_URL}/users/${userId}/groups`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`
    }
  }).then(async (res2) => {
    if (!res2.ok) throw await res2.json();
    return res2.json();
  }).catch((err) => {
    error = err.detail;
    return null;
  });
  if (error) {
    throw error;
  }
  return res;
};
function Badge($$renderer, $$props) {
  let type = fallback($$props["type"], "info");
  let content = fallback($$props["content"], "");
  const classNames = {
    info: "bg-blue-500/20 text-blue-700 dark:text-blue-200 ",
    success: "bg-green-500/20 text-green-700 dark:text-green-200",
    warning: "bg-yellow-500/20 text-yellow-700 dark:text-yellow-200",
    error: "bg-red-500/20 text-red-700 dark:text-red-200",
    muted: "bg-gray-500/20 text-gray-700 dark:text-gray-200"
  };
  $$renderer.push(`<div${attr_class(` text-xs font-medium ${stringify(classNames[type] ?? classNames["info"])} w-fit px-[5px] rounded-lg uppercase line-clamp-1 mr-0.5`)}>${escape_html(content)}</div>`);
  bind_props($$props, { type, content });
}
export {
  Badge as B,
  getUsers as a,
  getAndUpdateUserLocation as b,
  getUserInfoById as c,
  getUserSettings as d,
  getUserGroupsById as g,
  searchUsers as s,
  updateUserSettings as u
};
//# sourceMappingURL=Badge.js.map

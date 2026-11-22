// Small DOM helper: el(tag, attributes, ...children).
export const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style" && typeof v === "object") {
      for (const [prop, val] of Object.entries(v)) node.style.setProperty(prop, val);
    }
    else if (typeof v === "object" || (k in node && typeof v !== "string")) node[k] = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  node.append(...children.flat().filter((c) => c != null));
  return node;
};

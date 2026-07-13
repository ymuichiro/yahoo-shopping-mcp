PRODUCT_UI_URI = "ui://yahoo-shopping/product-carousel-v4.html"
PRODUCT_UI_META = {
    "ui": {
        "prefersBorder": False,
        "csp": {
            "resourceDomains": ["https://item-shopping.c.yimg.jp"],
            "connectDomains": [],
        },
    },
}

PRODUCT_CAROUSEL_HTML = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Yahoo!ショッピング商品</title>
  <style>
    :root { color: #202124; font: 14px/1.45 system-ui, sans-serif; }
    html, body { margin: 0; overflow: hidden; }
    #status { margin: 0 4px 6px; color: #5f6368; }
    #products { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(220px, 75%); gap: 12px; overflow-x: auto; overflow-y: hidden; padding: 4px 4px 10px; scroll-snap-type: x mandatory; scrollbar-width: thin; }
    #products::-webkit-scrollbar { height: 10px; }
    #products::-webkit-scrollbar-thumb { border-radius: 5px; background: #9aa0a6; }
    .card { scroll-snap-align: start; overflow: hidden; border: 1px solid #d9dce1; border-radius: 16px; background: #fff; }
    .image { aspect-ratio: 1; display: grid; place-items: center; background: #f5f6f7; color: #667085; }
    .image img { width: 100%; height: 100%; object-fit: contain; }
    .body { display: grid; gap: 8px; padding: 12px; }
    h3 { margin: 0; font-size: 14px; line-height: 1.45; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
    .price { font-size: 16px; } .seller, .stock { color: #5f6368; } button { justify-self: start; border: 0; border-radius: 8px; padding: 8px 10px; background: #0b57d0; color: #fff; cursor: pointer; } #attribution { margin: 8px 4px 0; font-size: 11px; color: #5f6368; }
  </style>
</head>
<body>
  <div id="status" aria-live="polite">商品を読み込んでいます…</div>
  <div id="products"></div>
  <div id="attribution"><span style="margin:15px 15px 15px 15px"><a href="https://developer.yahoo.co.jp/sitemap/">Web Services by Yahoo! JAPAN</a></span></div>
  <script>
    const status = document.getElementById("status");
    const container = document.getElementById("products");
    let requestId = 1;
    const pending = new Map();
    const notify = (method, params = {}) => window.parent.postMessage({ jsonrpc: "2.0", method, params }, "*");
    const request = (method, params) => new Promise((resolve, reject) => {
      const id = requestId++;
      pending.set(id, { resolve, reject });
      window.parent.postMessage({ jsonrpc: "2.0", id, method, params }, "*");
    });
    const showError = (message) => { status.textContent = message; container.replaceChildren(); };
    const productUrl = (value) => {
      try {
        const url = new URL(value);
        const hosts = new Set(["shopping.yahoo.co.jp", "store.shopping.yahoo.co.jp", "paypaymall.yahoo.co.jp"]);
        return url.protocol === "https:" && hosts.has(url.hostname) ? url.href : null;
      }
      catch { return null; }
    };
    const imageUrl = (value) => {
      try { const url = new URL(value); return url.protocol === "https:" && url.hostname === "item-shopping.c.yimg.jp" ? url.href : null; }
      catch { return null; }
    };
    const showProducts = (products = []) => {
      if (!products.length) { showError("該当する商品はありません。"); return; }
      status.textContent = `${products.length}件の商品`;
      container.replaceChildren(...products.map((product) => {
        const card = document.createElement("article"); card.className = "card";
        const image = document.createElement("div"); image.className = "image";
        const safeImageUrl = imageUrl(product.imageUrl);
        if (safeImageUrl) { const img = document.createElement("img"); img.src = safeImageUrl; img.alt = product.title || "商品画像"; img.onerror = () => { img.remove(); image.textContent = "画像なし"; }; image.append(img); }
        else image.textContent = "画像なし";
        const body = document.createElement("div"); body.className = "body";
        const title = document.createElement("h3"); title.textContent = product.title;
        const price = document.createElement("strong"); price.className = "price"; price.textContent = product.priceText;
        const seller = document.createElement("small"); seller.className = "seller"; seller.textContent = product.sellerName || "販売者情報なし";
        const stock = document.createElement("small"); stock.className = "stock"; stock.textContent = product.inStock ? "在庫あり" : "在庫情報なし";
        body.append(title, price, seller, stock);
        const href = productUrl(product.url);
        if (href) { const button = document.createElement("button"); button.type = "button"; button.textContent = "Yahoo!ショッピングで見る"; button.addEventListener("click", () => request("ui/open-link", { url: href }).catch(() => showError("商品ページを開けませんでした。"))); body.append(button); }
        card.append(image, body); return card;
      }));
    };
    window.addEventListener("message", (event) => {
      if (event.source !== window.parent || event.data?.jsonrpc !== "2.0") return;
      const response = pending.get(event.data.id);
      if (response) { pending.delete(event.data.id); event.data.error ? response.reject(event.data.error) : response.resolve(event.data.result); return; }
      if (event.data.method === "ui/notifications/tool-result") showProducts(event.data.params?.structuredContent?.products);
      if (event.data.method === "ui/resource-teardown" && event.data.id !== undefined) window.parent.postMessage({ jsonrpc: "2.0", id: event.data.id, result: {} }, "*");
    });
    request("ui/initialize", {
      protocolVersion: "2026-01-26",
      appCapabilities: {},
      appInfo: { name: "yahoo-product-carousel", version: "4.0.0" }
    }).then(() => {
      notify("ui/notifications/initialized");
      const resize = () => notify("ui/notifications/size-changed", { height: document.documentElement.scrollHeight });
      new ResizeObserver(() => requestAnimationFrame(resize)).observe(document.documentElement);
      resize();
    }).catch(() => showError("商品カルーセルを初期化できませんでした。"));
  </script>
</body>
</html>"""

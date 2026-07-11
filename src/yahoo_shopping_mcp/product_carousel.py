PRODUCT_UI_URI = "ui://yahoo-shopping/product-carousel-v1.html"
PRODUCT_UI_META = {
    "ui": {
        "prefersBorder": False,
        "csp": {
            "resourceDomains": ["https://item-shopping.c.yimg.jp"],
            "connectDomains": [],
        },
    },
    "openai/widgetPrefersBorder": False,
    "openai/widgetCSP": {
        "resource_domains": ["https://item-shopping.c.yimg.jp"],
        "connect_domains": [],
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
    #products { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(220px, 75%); gap: 12px; overflow-x: auto; padding: 4px 4px 16px; scroll-snap-type: x mandatory; }
    .card { scroll-snap-align: start; overflow: hidden; border: 1px solid #d9dce1; border-radius: 16px; background: #fff; }
    .image { aspect-ratio: 1; display: grid; place-items: center; background: #f5f6f7; color: #667085; }
    .image img { width: 100%; height: 100%; object-fit: contain; }
    .body { display: grid; gap: 8px; padding: 12px; }
    h3 { margin: 0; font-size: 14px; line-height: 1.45; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
    .price { font-size: 16px; } .seller, .stock { color: #5f6368; } button { justify-self: start; border: 0; border-radius: 8px; padding: 8px 10px; background: #0b57d0; color: #fff; cursor: pointer; }
  </style>
</head>
<body>
  <div id="products" aria-live="polite"></div>
  <script>
    const container = document.getElementById("products");
    const productUrl = (value) => {
      try { const url = new URL(value); return url.protocol === "https:" && url.hostname === "store.shopping.yahoo.co.jp" ? url.href : null; }
      catch { return null; }
    };
    const showProducts = (products = []) => {
      container.replaceChildren(...products.map((product) => {
        const card = document.createElement("article"); card.className = "card";
        const image = document.createElement("div"); image.className = "image";
        if (product.imageUrl) { const img = document.createElement("img"); img.src = product.imageUrl; img.alt = ""; img.loading = "lazy"; img.onerror = () => { img.remove(); image.textContent = "画像なし"; }; image.append(img); }
        else image.textContent = "画像なし";
        const body = document.createElement("div"); body.className = "body";
        const title = document.createElement("h3"); title.textContent = product.title;
        const price = document.createElement("strong"); price.className = "price"; price.textContent = product.priceText;
        const seller = document.createElement("small"); seller.className = "seller"; seller.textContent = product.sellerName || "販売者情報なし";
        const stock = document.createElement("small"); stock.className = "stock"; stock.textContent = product.inStock ? "在庫あり" : "在庫情報なし";
        body.append(title, price, seller, stock);
        const href = productUrl(product.url);
        if (href) { const button = document.createElement("button"); button.type = "button"; button.textContent = "Yahoo!ショッピングで見る"; button.addEventListener("click", () => window.openai?.openExternal ? window.openai.openExternal({ href }) : window.open(href, "_blank", "noopener")); body.append(button); }
        card.append(image, body); return card;
      }));
    };
    const output = window.openai?.toolOutput; if (output?.products) showProducts(output.products);
    window.addEventListener("message", (event) => {
      if (event.source === window.parent && event.data?.jsonrpc === "2.0" && event.data?.method === "ui/notifications/tool-result") showProducts(event.data.params?.structuredContent?.products);
    });
  </script>
</body>
</html>"""

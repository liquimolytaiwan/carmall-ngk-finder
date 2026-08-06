(function () {
  "use strict";
  var DATA = null;
  var elBrand  = document.getElementById("sel-brand");
  var elModel  = document.getElementById("sel-model");
  var elYear   = document.getElementById("sel-year");
  var fldYear  = document.getElementById("field-year");
  var elResult = document.getElementById("result");

  function opt(value, label) {
    var o = document.createElement("option");
    o.value = value; o.textContent = label;
    return o;
  }
  function clearSelect(sel, placeholder) {
    sel.innerHTML = "";
    sel.appendChild(opt("", placeholder));
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[c];
    });
  }
  function modelLabel(m) { return m.cc ? m.name + "　" + m.cc + "cc" : m.name; }
  function entryLabel(e) {
    // The note ("平行輸入車", "駕訓車"…) is what separates two otherwise identical year
    // rows, so it has to be visible in the picker, not only in the result.
    var n = (e.notes && e.notes.length) ? "（" + e.notes.join("・") + "）" : "";
    return (e.year || "不分年份") + n;
  }

  // ---- load data ----
  fetch("data.json", { cache: "no-cache" })
    .then(function (r) { if (!r.ok) throw new Error("data load " + r.status); return r.json(); })
    .then(function (d) {
      DATA = d;
      clearSelect(elBrand, "請選擇廠牌");
      d.brands.forEach(function (b) {
        elBrand.appendChild(opt(b.en, b.tw ? b.en + "（" + b.tw + "）" : b.en));
      });
      postHeight();
    })
    .catch(function () {
      elResult.hidden = false;
      elResult.innerHTML = '<div class="rc"><div class="state">' + iconAlertBig() +
        '<h3>查詢系統載入失敗</h3><p>請稍後重新整理頁面，或直接洽詢客服</p></div></div>';
      postHeight();
    });

  // ---- cascade ----
  elBrand.addEventListener("change", function () {
    reset();
    clearSelect(elModel, "請選擇車款");
    var b = findBrand(elBrand.value);
    if (!b) { elModel.disabled = true; postHeight(); return; }
    b.models.forEach(function (m, i) { elModel.appendChild(opt(String(i), modelLabel(m))); });
    elModel.disabled = false;
    postHeight();
  });

  elModel.addEventListener("change", function () {
    hideResult();
    var m = currentModel();
    if (!m) { hideYear(); postHeight(); return; }
    // Only ask for a year when this bike actually has more than one. Asking on a bike
    // with a single fitment trains people to click past the step — and that step is the
    // whole point on the bikes that do change plug mid-life.
    if (m.entries.length === 1) {
      hideYear();
      render(m, m.entries[0]);
      return;
    }
    clearSelect(elYear, "請選擇出廠年份");
    m.entries.forEach(function (e, i) { elYear.appendChild(opt(String(i), entryLabel(e))); });
    fldYear.hidden = false;
    postHeight();
  });

  elYear.addEventListener("change", function () {
    var m = currentModel();
    if (!m || elYear.value === "") { hideResult(); postHeight(); return; }
    render(m, m.entries[parseInt(elYear.value, 10)]);
  });

  function reset() { hideResult(); hideYear(); }
  function hideResult() { elResult.hidden = true; elResult.innerHTML = ""; }
  function hideYear() { fldYear.hidden = true; clearSelect(elYear, "請選擇出廠年份"); }
  function findBrand(en) {
    if (!DATA) return null;
    return DATA.brands.filter(function (b) { return b.en === en; })[0];
  }
  function currentModel() {
    var b = findBrand(elBrand.value);
    if (!b || elModel.value === "") return null;
    return b.models[parseInt(elModel.value, 10)];
  }

  // ---- render ----
  function render(m, e) {
    var b = findBrand(elBrand.value);
    var notes = (e.notes && e.notes.length) ? e.notes.join("・") : "";
    var sub = [b.tw, m.name_ja && m.name_ja !== m.name ? m.name_ja : "", e.year, notes]
      .filter(Boolean).join("　");
    var head = '<div class="rc-top"><div class="rc-veh">' +
      esc(b.en + " " + modelLabel(m)) +
      (sub ? '<small>' + esc(sub) + '</small>' : "") + '</div></div>';

    var body = e.no_dx ? noDxHtml(e) : buyHtml(e);
    elResult.innerHTML = '<div class="rc">' + head +
      '<div class="rc-body">' + specHtml(e) + body + sourceHtml(m, e) + '</div></div>';
    elResult.hidden = false;
    postHeight();
  }

  // Spec table: what NGK lists for this bike, across all its plug lines. Columns are
  // built from what the row actually carries — the printed catalogue has no separate OEM
  // or platinum column, and rendering them as a wall of "—" reads as missing data.
  function specHtml(e) {
    var cols = [
      { th: "引擎", get: function (x) { return x.engine; } },
      { th: "原廠／標準", get: function (x) { return x.oem; } },
      { th: "MotoDX 釕合金", get: function (x) { return x.dx; }, dx: true },
      { th: "白金", get: function (x) { return x.gp; } },
      { th: "銥合金", get: function (x) { return x.ix; } }
    ].filter(function (c) {
      return e.engines.some(function (x) { return c.get(x); });
    });
    var rows = e.engines.map(function (x) {
      var tds = cols.map(function (c) {
        var v = c.get(x);
        return '<td data-th="' + esc(c.th) + '">' +
          (v ? (c.dx ? '<b class="dx">' + esc(v) + '</b>' : esc(v)) : "—") + '</td>';
      }).join("");
      return '<tr>' + tds + '<td data-th="支數">' +
        (x.count ? esc(x.count) + " 支" : "—") + '</td></tr>';
    }).join("");
    return '<div class="spec-title">適用規格</div>' +
      '<div class="spec-wrap"><table class="spec"><thead><tr>' +
      cols.map(function (c) { return '<th>' + esc(c.th) + '</th>'; }).join("") +
      '<th>支數</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
  }

  // Which list this bike came from, and — for the Taiwan list — the fact that it carries
  // no year breakdown. Saying so is the point of this rebuild: a bike answered without a
  // year is exactly the case where an early model can be sent the late model's plug.
  // Whether this particular answer is year-specific, and where it came from. The claim is
  // made per entry, not per source: the catalogue prints plenty of rows with no year at
  // all, and telling those users the result was segmented by production year would give
  // false confidence in exactly the case the warning exists to flag.
  function sourceHtml(m, e) {
    var where = m.src === "catalog" ? "NGK 原廠車款對照表"
      : m.src === "tw_table" ? "NGK 台灣機種別 MOTO DX 對照表"
      : "NGK 台灣官方適應表";
    // Keyed off this entry's own year range, not off which list it came from: the
    // catalogue prints plenty of undated rows, and NGK Taiwan does date some of its.
    if (e.year_from || e.year_to) {
      // State the range rather than "the year you picked" — most bikes have a single
      // dated row and never show the picker, so there was nothing for them to pick.
      return '<div class="note">' + iconInfo() +
        '<span>資料來自' + where + '，本結果適用出廠年份 <b>' + esc(e.year) +
        '</b>。</span></div>';
    }
    return '<div class="note note-warn">' + iconInfo() +
      '<span>資料來自' + where + '，該表<b>未標示此車款的出廠年份</b>。' +
      '同型車不同年份有可能改用不同火星塞，安裝前請對照車主手冊或洽客服再確認。</span></div>';
  }

  function buyHtml(e) {
    var inStock = e.buys.filter(function (x) { return x.url; });
    // A bike needing two different plugs is only actually buyable when both are in
    // stock. Rendering just the available card would read as a complete recommendation
    // and let someone order half a set, so any shortfall falls through to the state below.
    if (inStock.length !== e.buys.length) {
      // Distinguish "we don't carry it" from "we carry it but not enough for this bike",
      // and quote the real numbers so the customer knows what to ask客服 for.
      var lines = e.buys.map(function (x) {
        var s = '<b>' + esc(x.sku) + '</b>' + (x.need != null ? '　需 ' + x.need + ' 支' : "");
        if (x.url) return s + '　✓ 有現貨';
        if (x.stock != null) return s + '　目前庫存 ' + x.stock + ' 支';
        return s + '　未販售';
      }).join("<br>");
      return '<div class="state">' + iconAlertBig() +
        '<h3>此車款適用的 MotoDX 火星塞現貨不足</h3>' +
        '<p>' + lines + '<br>請洽客服協助訂購</p>' +
        '<a class="cta secondary" href="https://www.carmall.com.tw/categories/brandlist/ngk" ' +
        'target="_blank" rel="noopener">查看全部 NGK 火星塞</a></div>';
    }
    var title = '<div class="opt-title">MotoDX 釕合金火星塞　<span>' +
      (inStock.length > 1 ? '此車需 ' + inStock.length + ' 種規格，皆需購買' : '點選前往購買') +
      '</span></div>';
    return title + inStock.map(card).join("") + trustHtml();
  }

  function card(x) {
    // x.need is null when no source states this bike's plug count. Quoting "此車需 1 支"
    // then would be a guess printed as a fact, and a twin owner would order half a set.
    var need = x.need;
    var qtyLine = need == null
      ? '單支 $' + fmt(x.price) + '　請依引擎缸數選購數量'
      : need > 1
        ? '單支 $' + fmt(x.price) + '　×　此車需 ' + need + ' 支'
        : '單支 $' + fmt(x.price) + '　此車需 1 支';
    var lowStock = (x.stock != null && x.stock > 0 && x.stock <= 3)
      ? '<span class="tag tag-low">僅剩 ' + x.stock + ' 件</span>' : "";
    var priceHtml = (need != null && need > 1)
      ? '<div class="opt-price"><span class="unitp">共 ' + need + ' 支</span><span class="now">$' +
        fmt(x.total) + '</span></div>'
      : '<div class="opt-price"><span class="now">$' + fmt(x.price) + '</span></div>';
    return '<a class="opt" href="' + esc(x.url) + '" target="_blank" rel="noopener">' +
      '<div class="opt-main"><div class="opt-name">' + esc(x.sku) +
      '<span class="tag tag-dx">釕合金 MotoDX</span>' + lowStock + '</div>' +
      '<div class="opt-sub">' + qtyLine + '</div></div>' +
      '<div class="opt-right">' + priceHtml + cart() + '</div></a>';
  }

  // NGK simply does not make a MotoDX plug for some bikes (mostly large-displacement
  // sports models). Show the spec honestly instead of substituting a near-miss part.
  function noDxHtml(e) {
    var rec = e.recommend || (e.engines[0] && e.engines[0].oem) || "";
    return '<div class="state">' + iconWrench() +
      '<h3>此車款 NGK 未推出 MotoDX 釕合金規格</h3>' +
      '<p>' + (rec ? '原廠／建議規格為 <b>' + esc(rec) + '</b>，' : "") +
      '本店目前主打的 MotoDX 系列不適用於此車款。<br>如需選購其他系列火星塞，請洽客服協助</p>' +
      '<a class="cta secondary" href="https://www.carmall.com.tw/categories/brandlist/ngk" ' +
      'target="_blank" rel="noopener">查看全部 NGK 火星塞</a>' +
      '</div>';
  }

  function trustHtml() {
    return '<div class="note">' + iconInfo() +
      '<span>釕合金 MotoDX 為 NGK 目前最高階的機車火星塞，較原廠鎳合金塞壽命更長、點火更穩定。' +
      '價格與庫存每日同步，實際成交以商品頁為準。</span></div>';
  }

  function fmt(n) {
    if (n == null) return "-";
    return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  // ---- icons ----
  function cart() { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.7 13.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L23 6H6"/></svg>'; }
  function iconWrench() { return '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="#2b2b6e" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.3 2.3-2.7-.7-.7-2.7z"/></svg>'; }
  function iconAlertBig() { return '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="#b9892b" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12" y2="17"/></svg>'; }
  function iconInfo() { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="8"/></svg>'; }

  // ---- iframe auto-height ----
  // Measure the content element, NOT documentElement.scrollHeight: the latter is clamped
  // to the viewport, and inside an iframe the viewport IS the height we just set. That
  // makes the reported height monotonically non-decreasing, so the frame can grow for a
  // result but never shrink back — leaving a tall blank gap on phones.
  var elRoot = document.getElementById("pf");
  function postHeight() {
    try {
      var h = Math.ceil(elRoot.getBoundingClientRect().height);
      if (h > 0) parent.postMessage({ type: "carmallPlugHeight", height: h }, "*");
    } catch (e) {}
  }
  window.addEventListener("load", postHeight);
  window.addEventListener("resize", postHeight);
  if (window.ResizeObserver) { new ResizeObserver(postHeight).observe(elRoot); }
})();

/* SocialScoop frontend
   หมายเหตุ: เนื้อหาจากโพสต์ (คำบรรยาย ชื่อ ลิงก์) ถูกใส่ผ่าน textContent เสมอ
   ไม่ใช่ innerHTML เพื่อไม่ให้ HTML ในคำบรรยายถูกรันเป็นโค้ด */

(function () {
  "use strict";

  var AI_ENABLED = (window.SOCIALSCOOP || {}).aiEnabled === true;

  var $ = function (id) { return document.getElementById(id); };

  var form = $("fetch-form");
  var urlInput = $("url-input");
  var fetchBtn = $("fetch-btn");
  var clearBtn = $("clear-btn");
  var chipRow = $("chip-row");
  var formError = $("form-error");
  var skeleton = $("skeleton");
  var resultEl = $("result");
  var toastEl = $("toast");

  var state = { url: null, details: null, downloading: false };
  var toastTimer = null;

  /* ---------- ธีม ---------- */
  var themeToggle = $("theme-toggle");
  var savedTheme = null;
  try { savedTheme = localStorage.getItem("socialscoop-theme"); } catch (e) { /* โหมดส่วนตัว */ }
  if (savedTheme === "dark" || savedTheme === "light") {
    document.documentElement.setAttribute("data-theme", savedTheme);
  }
  themeToggle.addEventListener("click", function () {
    var current = document.documentElement.getAttribute("data-theme");
    if (!current) {
      var prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      current = prefersDark ? "dark" : "light";
    }
    var next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("socialscoop-theme", next); } catch (e) { /* ไม่เป็นไร */ }
  });

  /* ---------- ตัวช่วย ---------- */
  function icon(paths, extraAttrs) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.8");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    if (extraAttrs) {
      Object.keys(extraAttrs).forEach(function (k) { svg.setAttribute(k, extraAttrs[k]); });
    }
    paths.forEach(function (d) {
      var p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", d);
      svg.appendChild(p);
    });
    return svg;
  }

  var ICONS = {
    copy: ["M9 9h9a2 2 0 0 1 2 2v9H9z", "M5 15V5a2 2 0 0 1 2-2h10"],
    check: ["M20 6 9 17l-5-5"],
    download: ["M12 3v12", "m7 11 5 5 5-5", "M4 19h16"],
    bag: ["M6 8h12l-1 12H7L6 8Z", "M9 8V6a3 3 0 0 1 6 0v2"],
    heart: ["M12 21s-7.2-4.5-9.6-9C.8 8 2.3 4.3 6 4.3c2 0 3.5 1 4 2.4.5-1.4 2-2.4 4-2.4 3.7 0 5.2 3.7 3.6 7.7-2.4 4.5-9.6 9-9.6 9z"],
    comment: ["M4 4h16v12H8l-4 4V4z"],
    eye: ["M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z", "M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"]
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function showToast(message) {
    toastEl.textContent = message;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.hidden = true; }, 2600);
  }

  function copyText(text, btn, label) {
    var done = function () {
      showToast(label || "คัดลอกแล้ว");
      if (!btn) return;
      var original = btn.cloneNode(true);
      btn.classList.add("copied");
      btn.textContent = "";
      btn.appendChild(icon(ICONS.check));
      if (label) btn.appendChild(document.createTextNode("คัดลอกแล้ว"));
      setTimeout(function () {
        btn.classList.remove("copied");
        btn.textContent = "";
        while (original.firstChild) btn.appendChild(original.firstChild);
      }, 1400);
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text, done); });
    } else {
      fallbackCopy(text, done);
    }
  }

  // สำรองไว้เมื่อ Clipboard API ใช้ไม่ได้ — เกิดเสมอเมื่อเปิดผ่าน http:// ธรรมดา
  // (เช่นเปิดจาก iPhone มาที่เครื่องนี้ในวง Wi-Fi เดียวกัน) เพราะ Clipboard API
  // ต้องการ secure context คือ https หรือ localhost เท่านั้น
  //
  // iOS Safari มีข้อกำหนดต่างจากเบราว์เซอร์อื่น: ta.select() บน textarea ที่เป็น
  // readonly จะไม่เลือกข้อความให้จริง ต้องตั้ง contentEditable แล้วใช้ Range
  // ร่วมกับ setSelectionRange จึงจะคัดลอกได้
  function fallbackCopy(text, done) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.contentEditable = "true";
    ta.readOnly = false;
    // วางไว้ในจอจริงแต่มองไม่เห็น ถ้าใช้ display:none หรือย้ายออกนอกจอ
    // iOS จะไม่ยอมเลือกข้อความให้ และต้อง >=16px กันหน้าเด้งซูมชั่ววินาที
    ta.style.cssText =
      "position:fixed;top:50%;left:0;width:1px;height:1px;padding:0;border:none;" +
      "outline:none;opacity:0;font-size:16px;";
    document.body.appendChild(ta);

    var ok = false;
    try {
      var range = document.createRange();
      range.selectNodeContents(ta);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      ta.setSelectionRange(0, text.length);
      ok = document.execCommand("copy");
    } catch (e) {
      ok = false;
    }

    document.body.removeChild(ta);
    if (ok) {
      done();
    } else {
      showToast("คัดลอกอัตโนมัติไม่ได้ — แตะค้างที่ข้อความเพื่อคัดลอกเอง");
    }
  }

  function copyButton(text, ariaLabel) {
    var btn = el("button", "copy-icon-btn");
    btn.type = "button";
    btn.setAttribute("aria-label", ariaLabel);
    btn.appendChild(icon(ICONS.copy));
    btn.addEventListener("click", function () { copyText(text, btn); });
    return btn;
  }

  /* ---------- ตรวจแพลตฟอร์มตอนพิมพ์/วาง ---------- */
  function hostOf(value) {
    var raw = (value || "").trim();
    if (!raw) return "";
    if (raw.indexOf("//") === -1) raw = "https://" + raw;
    try { return new URL(raw).hostname.toLowerCase().replace(/^www\./, ""); }
    catch (e) { return ""; }
  }

  function detectPlatform(value) {
    var host = hostOf(value);
    if (!host) return null;
    if (host === "tiktok.com" || /\.tiktok\.com$/.test(host)) return "tiktok";
    if (host === "instagram.com" || /\.instagram\.com$/.test(host)) return "instagram";
    if (/^(.*\.)?threads\.(net|com)$/.test(host)) return "threads";
    // twitter.com คือชื่อเดิมของ x.com — คนยังคัดลอกลิงก์แบบเดิมมาใช้อยู่มาก
    if (/^(.*\.)?(x|twitter)\.com$/.test(host)) return "x";
    return null;
  }

  function updateChips() {
    var platform = detectPlatform(urlInput.value);
    Array.prototype.forEach.call(chipRow.querySelectorAll(".chip"), function (chip) {
      chip.classList.toggle("on", chip.dataset.platform === platform);
    });
  }

  /* ---------- ช่องวางลิงก์: วางลิงก์ใหม่ทับได้เลย ไม่ต้องลบของเก่าทิ้งก่อน ---------- */
  function syncClearBtn() {
    clearBtn.hidden = urlInput.value.length === 0;
  }

  urlInput.addEventListener("input", function () {
    updateChips();
    syncClearBtn();
  });

  // แตะเข้ามาครั้งแรก = เลือกลิงก์เก่าทั้งเส้นให้เลย พิมพ์หรือวางทับได้ทันที
  var selectAllOnClick = false;
  urlInput.addEventListener("focus", function () {
    if (!urlInput.value) return;
    selectAllOnClick = true;
    urlInput.select();
  });
  urlInput.addEventListener("mouseup", function (event) {
    // ปกติเบราว์เซอร์จะยกเลิก selection ทิ้งทันทีหลัง focus ต้องกันไว้ตรงนี้
    // กันเฉพาะคลิกแรกเท่านั้น คลิกครั้งต่อไปยังวางเคอร์เซอร์แก้กลางลิงก์ได้ตามปกติ
    if (!selectAllOnClick) return;
    event.preventDefault();
    selectAllOnClick = false;
  });
  urlInput.addEventListener("blur", function () { selectAllOnClick = false; });

  clearBtn.addEventListener("click", function () {
    urlInput.value = "";
    updateChips();
    syncClearBtn();
    setError(null);
    urlInput.focus();
  });

  // เบราว์เซอร์คืนค่าเดิมให้เองได้เมื่อกดย้อนกลับมาหน้านี้ (bfcache) ซึ่งไม่ยิง input
  // event ให้ ต้องซิงก์สถานะตอนเริ่มด้วย ไม่งั้นช่องมีลิงก์อยู่แต่ปุ่มล้างกับ chip ไม่ขึ้น
  updateChips();
  syncClearBtn();

  // วางลิงก์ที่รองรับ = ดึงข้อมูลให้เลย ไม่ต้องกดปุ่มซ้ำอีกที
  // เช็กก่อนว่าเป็นลิงก์ที่รองรับจริงถึงจะยิง กันกรณีวางข้อความมั่วแล้วเสียเที่ยวเปล่า
  urlInput.addEventListener("paste", function (event) {
    var clip = event.clipboardData || window.clipboardData;
    if (!clip) return;

    var text = "";
    try { text = (clip.getData("text") || "").trim(); } catch (e) { return; }
    if (!text || !detectPlatform(text)) return;

    event.preventDefault();
    urlInput.value = text;
    updateChips();
    syncClearBtn();
    requestFetch();
  });

  /* ---------- เรียก API ---------- */
  function postJSON(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) {
          throw new Error(data.detail || ("เกิดข้อผิดพลาด (HTTP " + res.status + ")"));
        }
        return data;
      });
    });
  }

  function setError(message) {
    if (!message) {
      formError.hidden = true;
      formError.textContent = "";
      return;
    }
    formError.textContent = message;
    formError.hidden = false;
  }

  function setLoading(isLoading) {
    fetchBtn.disabled = isLoading;
    fetchBtn.classList.toggle("loading", isLoading);
    skeleton.hidden = !isLoading;
    if (isLoading) resultEl.hidden = true;
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    requestFetch();
  });

  function requestFetch() {
    var url = urlInput.value.trim();
    if (!url) return;

    setError(null);
    setLoading(true);

    postJSON("/api/fetch", { url: url })
      .then(function (data) {
        state.url = data.url;
        state.details = data.details;
        renderResult(data.details);
      })
      .catch(function (err) {
        setError(err.message);
        resultEl.hidden = true;
      })
      .finally(function () { setLoading(false); });
  }

  /* ---------- แสดงผลลัพธ์ ---------- */
  function detailRow(label, valueNode, copySource, ariaLabel) {
    var row = el("div", "detail-row");
    row.appendChild(el("div", "detail-label", label));
    row.appendChild(valueNode);
    if (copySource) row.appendChild(copyButton(copySource, ariaLabel));
    return row;
  }

  function renderResult(details) {
    resultEl.textContent = "";

    var grid = el("div", "result-grid");

    // รูปปก — ถ้าโหลดไม่ได้ให้แทนด้วยกล่องข้อความ ไม่ปล่อยรูปแตก
    if (details.thumbnail) {
      var img = document.createElement("img");
      img.className = "thumb";
      img.src = details.thumbnail;
      img.alt = "ภาพปกของโพสต์";
      img.loading = "lazy";
      img.addEventListener("error", function () {
        var fb = el("div", "thumb-fallback", "ไม่มีภาพปก");
        if (img.parentNode) img.parentNode.replaceChild(fb, img);
      });
      grid.appendChild(img);
    } else {
      grid.appendChild(el("div", "thumb-fallback", "ไม่มีภาพปก"));
    }

    var meta = el("div");

    if (details.title) meta.appendChild(el("h2", "r-title", details.title));

    var subParts = [];
    if (details.uploader) subParts.push("@" + String(details.uploader).replace(/^@/, ""));
    if (details.platform) subParts.push(details.platform);
    if (details.resolution) subParts.push(details.resolution);
    if (subParts.length) meta.appendChild(el("p", "r-sub", subParts.join(" · ")));

    meta.appendChild(buildDetailsCard(details));
    meta.appendChild(buildActionRow(details));
    meta.appendChild(buildAiPanel(details));

    grid.appendChild(meta);
    resultEl.appendChild(grid);
    resultEl.hidden = false;
  }

  function buildDetailsCard(details) {
    var card = el("div", "details-card");

    var head = el("div", "details-head");
    head.appendChild(el("span", "details-title", "รายละเอียดโพสต์"));

    var copyAll = el("button", "copy-all-btn");
    copyAll.type = "button";
    copyAll.appendChild(icon(ICONS.copy));
    copyAll.appendChild(document.createTextNode("คัดลอกทั้งหมด"));
    copyAll.addEventListener("click", function () {
      copyText(buildPlainText(details), copyAll, "คัดลอกแล้ว");
    });
    head.appendChild(copyAll);
    card.appendChild(head);

    // คำบรรยาย
    if (details.caption) {
      var cap = el("div", "detail-value quote", details.caption);
      card.appendChild(detailRow("คำบรรยาย", cap, details.caption, "คัดลอกคำบรรยาย"));
    } else {
      var empty = el("div", "detail-value hint", "โพสต์นี้ไม่มีคำบรรยาย");
      card.appendChild(detailRow("คำบรรยาย", empty, null));
    }

    // ลิงก์ Shopee — แยกแถวละลิงก์ ไฮไลต์ต่างจากแถวอื่น
    (details.shopee_links || []).forEach(function (link) {
      var row = el("div", "detail-row affiliate");

      var label = el("div", "detail-label");
      label.appendChild(icon(ICONS.bag));
      label.appendChild(document.createTextNode("Shopee"));
      row.appendChild(label);

      var wrap = el("div", "detail-value");
      var linkAnchor = el("a", "detail-value mono", link);
      linkAnchor.href = link;
      linkAnchor.target = "_blank";
      linkAnchor.rel = "noopener noreferrer";
      wrap.appendChild(linkAnchor);
      wrap.appendChild(el("div", "hint",
        "พบในคำบรรยาย — แตะเพื่อเปิด Shopee (เปิดแอปถ้าติดตั้งไว้) แล้วสร้างลิงก์ affiliate ของคุณเองจากหน้าสินค้านั้น"));
      row.appendChild(wrap);

      row.appendChild(copyButton(link, "คัดลอกลิงก์ Shopee"));
      card.appendChild(row);
    });

    // แฮชแท็ก
    if (details.hashtags && details.hashtags.length) {
      var chips = el("div", "tag-chips");
      details.hashtags.forEach(function (tag) { chips.appendChild(el("span", "tag-chip", tag)); });
      card.appendChild(detailRow("แฮชแท็ก", chips, details.hashtags.join(" "), "คัดลอกแฮชแท็ก"));
    }

    // ยอดมีส่วนร่วม — ซ่อนทั้งแถวถ้าไม่มีข้อมูลเลย ไม่แสดง 0 ให้เข้าใจผิด
    var stats = details.stats || {};
    var statDefs = [
      { key: "like", icon: ICONS.heart, label: "ถูกใจ" },
      { key: "comment", icon: ICONS.comment, label: "ความคิดเห็น" },
      { key: "view", icon: ICONS.eye, label: "การเข้าชม" }
    ].filter(function (d) { return stats[d.key]; });

    if (statDefs.length) {
      var group = el("div", "stat-group");
      statDefs.forEach(function (d) {
        var item = el("span", "stat-item");
        item.appendChild(icon(d.icon));
        item.appendChild(document.createTextNode(stats[d.key]));
        item.title = d.label;
        item.setAttribute("aria-label", d.label + " " + stats[d.key]);
        group.appendChild(item);
      });
      card.appendChild(detailRow("ยอดมีส่วนร่วม", group, null));
    }

    // ลิงก์ต้นฉบับ
    if (details.webpage_url) {
      var linkNode = el("div", "detail-value mono", details.webpage_url);
      card.appendChild(detailRow("ลิงก์ต้นฉบับ", linkNode, details.webpage_url, "คัดลอกลิงก์ต้นฉบับ"));
    }

    return card;
  }

  function buildPlainText(details) {
    var lines = [];
    if (details.title) lines.push(details.title, "");
    if (details.caption) lines.push(details.caption, "");
    (details.shopee_links || []).forEach(function (link) {
      lines.push("ลิงก์ Shopee ที่พบ: " + link);
    });
    if ((details.shopee_links || []).length) lines.push("");
    var stats = details.stats || {};
    var statText = [];
    if (stats.like) statText.push("ถูกใจ " + stats.like);
    if (stats.comment) statText.push("ความคิดเห็น " + stats.comment);
    if (stats.view) statText.push("การเข้าชม " + stats.view);
    if (statText.length) lines.push(statText.join(" · "));
    if (details.webpage_url) lines.push(details.webpage_url);
    return lines.join("\n").trim();
  }

  function buildActionRow(details) {
    var row = el("div", "action-row");

    // Threads โพสต์ข้อความล้วน (ไม่มีรูป/วิดีโอ) media_type จะเป็น null ตรงๆ —
    // ต่างจาก TikTok/Instagram ที่ไม่มีฟิลด์นี้เลย (undefined ก็ยังถือว่ามีวิดีโอเสมอ
    // ตามพฤติกรรมเดิม) ไม่งั้นจะมีปุ่มที่กดแล้วพังทุกครั้งให้ผู้ใช้เห็น
    if (details.media_type !== null) {
      var isImage = details.media_type === "image";
      var mediaBtn = el("button", "btn-ghost");
      mediaBtn.type = "button";
      mediaBtn.appendChild(icon(ICONS.download));
      var mediaLabel = isImage
        ? "รูปภาพ"
        : (details.resolution ? "วิดีโอ " + details.resolution : "วิดีโอ");
      mediaBtn.appendChild(document.createTextNode(mediaLabel));
      mediaBtn.addEventListener("click", function () { startDownload(mediaBtn, isImage); });
      row.appendChild(mediaBtn);
    }

    if (details.caption) {
      var capBtn = el("button", "btn-ghost");
      capBtn.type = "button";
      capBtn.appendChild(icon(ICONS.download));
      capBtn.appendChild(document.createTextNode("คำบรรยาย (.txt)"));
      capBtn.addEventListener("click", function () {
        saveTextFile(buildPlainText(details), safeName(details) + ".txt");
      });
      row.appendChild(capBtn);
    }

    var jsonBtn = el("button", "btn-ghost");
    jsonBtn.type = "button";
    jsonBtn.appendChild(icon(ICONS.download));
    jsonBtn.appendChild(document.createTextNode("ข้อมูลทั้งหมด (.json)"));
    jsonBtn.addEventListener("click", function () {
      saveTextFile(JSON.stringify(details, null, 2), safeName(details) + ".json");
    });
    row.appendChild(jsonBtn);

    return row;
  }

  function safeName(details) {
    var base = (details.title || "socialscoop").slice(0, 60);
    return base.replace(/[\\/:*?"<>|\n\r\t]+/g, "_").trim() || "socialscoop";
  }

  function saveTextFile(text, filename) {
    var blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    // iOS Safari รุ่นเก่าไม่รองรับแอตทริบิวต์ download กับ blob: จะเปิดไฟล์เป็นหน้าใหม่แทน
    // อย่างน้อยผู้ใช้ยังเห็นเนื้อหาแล้วคัดลอกเองได้ ไม่ใช่กดแล้วเงียบไปเฉย ๆ
    if (!("download" in a)) {
      a.target = "_blank";
      a.rel = "noopener";
      showToast("อุปกรณ์นี้จะเปิดไฟล์แทนการบันทึก");
    }
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function startDownload(btn, isImage) {
    if (state.downloading || !state.url) return;
    state.downloading = true;
    btn.disabled = true;
    var originalNodes = Array.prototype.slice.call(btn.childNodes);
    btn.textContent = "กำลังดาวน์โหลด...";
    showToast(isImage ? "กำลังดาวน์โหลดรูปภาพ อาจใช้เวลาสักครู่" : "กำลังดาวน์โหลดวิดีโอ อาจใช้เวลาสักครู่");

    postJSON("/api/download", { url: state.url })
      .then(function (data) {
        window.location.href = "/api/file/" + encodeURIComponent(data.filename);
        showToast("ดาวน์โหลดสำเร็จ");
      })
      .catch(function (err) {
        setError(err.message);
        showToast("ดาวน์โหลดไม่สำเร็จ");
      })
      .finally(function () {
        state.downloading = false;
        btn.disabled = false;
        btn.textContent = "";
        originalNodes.forEach(function (n) { btn.appendChild(n); });
      });
  }

  /* ---------- แผง AI ---------- */
  function buildAiPanel(details) {
    var panel = el("div", "ai-panel");
    panel.appendChild(el("div", "ai-label", "ถาม AI เกี่ยวกับโพสต์นี้"));

    if (!details.caption) {
      panel.appendChild(el("p", "ai-disabled-note",
        "โพสต์นี้ไม่มีข้อความให้ AI วิเคราะห์"));
      return panel;
    }
    if (!AI_ENABLED) {
      panel.appendChild(el("p", "ai-disabled-note",
        "ยังไม่ได้ตั้งค่า OPENROUTER_API_KEY — คัดลอกไฟล์ .env.example เป็น .env แล้วใส่คีย์จาก openrouter.ai เพื่อเปิดใช้"));
      return panel;
    }

    var log = el("div", "ai-log");
    panel.appendChild(log);

    var aiForm = el("form", "ai-form");
    var input = document.createElement("input");
    input.type = "text";
    input.placeholder = "เช่น สรุปให้หน่อย / สินค้านี้ราคาเท่าไหร่";
    input.setAttribute("aria-label", "คำถามเกี่ยวกับโพสต์นี้");
    input.maxLength = 1000;

    var sendBtn = el("button", "btn-teal", "ถาม");
    sendBtn.type = "submit";

    aiForm.appendChild(input);
    aiForm.appendChild(sendBtn);

    aiForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var question = input.value.trim();
      if (!question) return;

      var turn = el("div", "ai-turn");
      turn.appendChild(el("p", "ai-q", question));
      var answerNode = el("p", "ai-a", "กำลังคิด...");
      turn.appendChild(answerNode);
      log.appendChild(turn);

      input.value = "";
      input.disabled = true;
      sendBtn.disabled = true;

      postJSON("/api/ask", { caption: details.caption, question: question })
        .then(function (data) { answerNode.textContent = data.answer; })
        .catch(function (err) {
          answerNode.textContent = err.message;
          answerNode.classList.add("error");
        })
        .finally(function () {
          input.disabled = false;
          sendBtn.disabled = false;
          input.focus();
        });
    });

    panel.appendChild(aiForm);
    return panel;
  }

  updateChips();
})();

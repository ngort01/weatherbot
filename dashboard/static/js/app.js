/**
 * Thin chrome for the HTMX dashboard: tabs, drawer, auto-refresh, charts after swap.
 * Server renders HTML partials; this file does not build tables.
 */

const Dashboard = (() => {
  /** @type {string} */
  let activeTab = "overview";

  /** @type {number | null} */
  let autoTimer = null;

  function setActiveTab(tab) {
    activeTab = tab || "overview";
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-tab") === activeTab);
    });
    const refresh = document.getElementById("btn-refresh");
    if (refresh) {
      refresh.setAttribute("hx-get", `/partials/${activeTab}`);
      if (window.htmx) window.htmx.process(refresh);
    }
  }

  function openDrawer() {
    const drawer = document.getElementById("drawer");
    const backdrop = document.getElementById("drawer-backdrop");
    if (!drawer || !backdrop) return;
    backdrop.classList.remove("hidden");
    requestAnimationFrame(() => {
      backdrop.classList.add("open");
      drawer.classList.add("open");
    });
  }

  function closeDrawer() {
    const drawer = document.getElementById("drawer");
    const backdrop = document.getElementById("drawer-backdrop");
    if (!drawer || !backdrop) return;
    drawer.classList.remove("open");
    backdrop.classList.remove("open");
    setTimeout(() => backdrop.classList.add("hidden"), 200);
  }

  function initChartsIn(el) {
    if (typeof ChartKit !== "undefined") {
      ChartKit.initFromDom(el || document);
    }
  }

  function onAfterSwap(evt) {
    const target = evt.detail && evt.detail.target;
    if (target) initChartsIn(target);
    // Tab from swapped fragment
    const panel = target && target.querySelector
      ? target.querySelector("[data-tab]")
      : null;
    if (panel && panel.getAttribute("data-tab")) {
      setActiveTab(panel.getAttribute("data-tab"));
    }
  }

  function boot() {
    // Initial tab from URL or shell placeholder
    const params = new URLSearchParams(window.location.search);
    const tab = params.get("tab") || "overview";
    setActiveTab(tab);

    document.body.addEventListener("htmx:afterSwap", onAfterSwap);
    document.body.addEventListener("htmx:afterSettle", (evt) => {
      // OOB + nested scripts: re-init charts once settle completes
      const target = evt.detail && evt.detail.target;
      if (target) initChartsIn(target);
    });

    // Server HX-Trigger: {"wb:tab": "trades"}
    document.body.addEventListener("wb:tab", (evt) => {
      if (evt.detail) setActiveTab(evt.detail);
    });

    document.getElementById("drawer-close")?.addEventListener("click", closeDrawer);
    document.getElementById("drawer-backdrop")?.addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeDrawer();
    });

    document.getElementById("auto-refresh")?.addEventListener("change", (e) => {
      if (autoTimer) {
        clearInterval(autoTimer);
        autoTimer = null;
      }
      if (e.target instanceof HTMLInputElement && e.target.checked) {
        autoTimer = window.setInterval(() => {
          const btn = document.getElementById("btn-refresh");
          if (btn && window.htmx) window.htmx.trigger(btn, "click");
        }, 60_000);
      }
    });

    // Highlight tab buttons when clicked (before response)
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        setActiveTab(btn.getAttribute("data-tab") || "overview");
      });
    });
  }

  return { setActiveTab, openDrawer, closeDrawer, boot };
})();

window.Dashboard = Dashboard;
document.addEventListener("DOMContentLoaded", () => Dashboard.boot());

// Small, nonmodal game windows. Only their title bars capture pointer movement.
export function clampWindow(
  x,
  y,
  width,
  height,
  viewportWidth,
  viewportHeight,
) {
  const gap = 6;
  return {
    x: Math.max(gap, Math.min(x, viewportWidth - width - gap)),
    y: Math.max(gap, Math.min(y, viewportHeight - height - gap)),
  };
}
let front = 10;
export class GameWindow {
  constructor(element) {
    this.element = element;
    this.handle = element.querySelector("[data-drag-handle]");
    this.collapse = element.querySelector("[data-collapse]");
    this.collapseLabel = this.collapse.getAttribute("aria-label");
    this.collapse.addEventListener("click", () => this.fold());
    element.addEventListener("pointerdown", () => this.raise());
    element.addEventListener("focusin", () => this.raise());
    this.handle.addEventListener("dblclick", (e) => {
      if (!e.target.closest("button")) this.fold();
    });
    this.handle.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest("button")) return;
      const r = element.getBoundingClientRect();
      this.drag = {
        id: e.pointerId,
        x: e.clientX - r.left,
        y: e.clientY - r.top,
      };
      this.handle.setPointerCapture(e.pointerId);
      this.handle.focus({ preventScroll: true });
      e.preventDefault();
    });
    this.handle.addEventListener("pointermove", (e) => {
      if (this.drag?.id !== e.pointerId) return;
      this.move(e.clientX - this.drag.x, e.clientY - this.drag.y);
    });
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"])
      this.handle.addEventListener(type, () => {
        this.drag = null;
      });
    this.handle.addEventListener("keydown", (e) => {
      if (e.target !== this.handle) return;
      const delta = {
        ArrowLeft: [-1, 0],
        ArrowRight: [1, 0],
        ArrowUp: [0, -1],
        ArrowDown: [0, 1],
      }[e.key];
      if (!delta) return;
      e.preventDefault();
      const r = element.getBoundingClientRect(),
        step = e.shiftKey ? 32 : 8;
      this.move(r.left + delta[0] * step, r.top + delta[1] * step);
    });
    new ResizeObserver(() => this.ensureVisible()).observe(element);
    window.addEventListener("resize", () => this.ensureVisible());
  }
  raise() {
    this.element.style.zIndex = String(++front);
  }
  move(x, y) {
    const r = this.element.getBoundingClientRect();
    const p = clampWindow(x, y, r.width, r.height, innerWidth, innerHeight);
    Object.assign(this.element.style, {
      left: `${p.x}px`,
      top: `${p.y}px`,
      right: "auto",
      bottom: "auto",
    });
  }
  ensureVisible() {
    if (!this.element.getClientRects().length) return;
    const r = this.element.getBoundingClientRect();
    this.move(r.left, r.top);
  }
  fold(collapsed = !this.element.classList.contains("is-collapsed")) {
    this.element.classList.toggle("is-collapsed", collapsed);
    this.collapse.setAttribute("aria-expanded", String(!collapsed));
    this.collapse.setAttribute(
      "aria-label",
      collapsed
        ? this.collapseLabel.replace("折り畳む", "開く")
        : this.collapseLabel,
    );
    this.collapse.title = collapsed ? "開く" : "折り畳み";
    this.collapse.textContent = collapsed ? "+" : "−";
    this.ensureVisible();
  }
  show() {
    this.element.hidden = false;
    this.fold(false);
    this.ensureVisible();
    this.raise();
  }
}
export class AquariumMenu extends GameWindow {
  constructor() {
    super(document.getElementById("menu"));
    this.stage = document.getElementById("stage");
    this.panel = "aquarium";
    this.tabs = [...this.element.querySelectorAll("[data-panel]")];
    for (const button of this.tabs) {
      button.addEventListener("click", () =>
        this.showPanel(button.dataset.panel),
      );
      button.addEventListener("keydown", (e) => {
        const index = this.tabs.indexOf(button);
        const next = {
          ArrowLeft: (index + this.tabs.length - 1) % this.tabs.length,
          ArrowRight: (index + 1) % this.tabs.length,
          Home: 0,
          End: this.tabs.length - 1,
        }[e.key];
        if (next === undefined) return;
        e.preventDefault();
        this.showPanel(this.tabs[next].dataset.panel);
        this.tabs[next].focus();
      });
    }
    document
      .getElementById("menu-toggle")
      .addEventListener("click", () =>
        this.visible ? this.close() : this.open(),
      );
    document
      .getElementById("close-menu")
      .addEventListener("click", () => this.close());
  }
  get visible() {
    return !this.element.hidden;
  }
  showPanel(panel = this.panel) {
    this.panel = panel;
    for (const el of this.element.querySelectorAll("[data-content]"))
      el.hidden = el.dataset.content !== panel;
    for (const el of this.tabs) {
      const active = el.dataset.panel === panel;
      el.setAttribute("aria-selected", String(active));
      el.tabIndex = active ? 0 : -1;
    }
    this.ensureVisible();
  }
  open(panel = this.panel) {
    this.showPanel(panel);
    this.show();
    document
      .getElementById("menu-toggle")
      .setAttribute("aria-expanded", "true");
    if (panel === "processes") document.getElementById("search").focus();
    else this.tabs.find((el) => el.dataset.panel === panel).focus();
  }
  close() {
    this.element.hidden = true;
    document
      .getElementById("menu-toggle")
      .setAttribute("aria-expanded", "false");
    this.stage.focus({ preventScroll: true });
  }
}

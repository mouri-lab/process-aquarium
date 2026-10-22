// Settings are summoned over the aquarium; they never reserve screen space.
export class AquariumMenu {
  constructor() {
    this.dialog = document.getElementById("menu");
    this.stage = document.getElementById("stage");
    for (const button of document.querySelectorAll("[data-panel]"))
      button.addEventListener("click", () =>
        this.showPanel(button.dataset.panel),
      );
    document
      .getElementById("menu-toggle")
      .addEventListener("click", () => this.open());
    for (const id of ["resume", "close-menu"])
      document.getElementById(id).addEventListener("click", () => this.close());
    this.dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      this.close();
    });
    this.dialog.addEventListener("click", (event) => {
      if (event.target === this.dialog) {
        const r = this.dialog.getBoundingClientRect();
        if (
          event.clientX < r.left ||
          event.clientX > r.right ||
          event.clientY < r.top ||
          event.clientY > r.bottom
        )
          this.close();
      }
    });
  }
  get visible() {
    return this.dialog.open;
  }
  showPanel(panel = "aquarium") {
    const titles = {
      aquarium: ["A MOMENT UNDERWATER", "水槽"],
      processes: ["FIND A LITTLE LIFE", "魚を探す"],
      display: ["THE WAY YOU SEE", "描画"],
      host: ["ANOTHER AQUARIUM", "接続"],
      help: ["MAKE YOURSELF AT HOME", "操作ガイド"],
    };
    for (const el of document.querySelectorAll("[data-content]"))
      el.hidden = el.dataset.content !== panel;
    for (const el of document.querySelectorAll("[data-panel]")) {
      if (el.dataset.panel === panel) el.setAttribute("aria-current", "page");
      else el.removeAttribute("aria-current");
    }
    document.getElementById("menu-caption").textContent = titles[panel][0];
    document.getElementById("menu-title").textContent = titles[panel][1];
    if (panel === "processes") document.getElementById("search").focus();
  }
  open(panel = "aquarium") {
    if (!this.dialog.open) this.dialog.showModal();
    this.showPanel(panel);
  }
  close() {
    if (this.dialog.open) this.dialog.close();
    this.stage.focus({ preventScroll: true });
  }
}

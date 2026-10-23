// Installation is offered by the browser; ordinary HTTP still works without SW.
if (window.isSecureContext && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js", { updateViaCache: "none" })
      .catch((error) => console.warn("Offline shell registration failed", error));
  });
}

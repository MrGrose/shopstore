export function openStoreCompany() {
  window.dispatchEvent(new CustomEvent("store:company:open"));
}

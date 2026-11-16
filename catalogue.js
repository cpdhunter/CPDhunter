/* CPD Hunter - catalogue eligibility. Uses official registration.status only. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.CPDCatalogue = Object.freeze(api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function hasTimeSlot(event) {
    return /\d{1,2}:\d{2}/.test(String((event && event.time) || ""));
  }

  function isRegistrationClosed(event) {
    const reg = event && event.registration;
    return !!(reg && typeof reg === "object" && reg.status === "CLOSED");
  }

  function isCatalogueEligible(event) {
    return !!event && hasTimeSlot(event) && !isRegistrationClosed(event);
  }

  function isVisibleFuture(event, today) {
    return isCatalogueEligible(event) && !!event.date && event.date >= String(today || "");
  }

  function catalogueEvents(events, today) {
    const list = Array.isArray(events) ? events : [];
    if (today) return list.filter((e) => isVisibleFuture(e, today));
    return list.filter(isCatalogueEligible);
  }

  function searchCatalogue(events, query, today) {
    const q = String(query || "").trim().toLowerCase();
    return catalogueEvents(events, today).filter((e) => {
      if (!q) return true;
      const hay = `${e.name || ""} ${e.org || ""} ${e.source || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }

  function canStartPrepareRegistration(event) {
    return !isRegistrationClosed(event);
  }

  function isLocallyRegistered(state) {
    const st = state && typeof state === "object" ? state.state : state;
    return st === "registered_manual";
  }

  function remainsInMyEvents(localState) {
    const st = localState && typeof localState === "object" ? localState.state : localState;
    return st === "registered_manual" || st === "opened";
  }

  function registrationNowClosedLabel(event, localState) {
    if (!isRegistrationClosed(event)) return "";
    const st = localState && typeof localState === "object" ? localState.state : localState;
    if (st === "opened" || st === "registered_manual") return "Registration now closed";
    return "Registration closed.";
  }

  return {
    hasTimeSlot,
    isRegistrationClosed,
    isCatalogueEligible,
    isVisibleFuture,
    catalogueEvents,
    searchCatalogue,
    canStartPrepareRegistration,
    isLocallyRegistered,
    remainsInMyEvents,
    registrationNowClosedLabel
  };
});

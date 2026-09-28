/**
 * OJ Microline schedule card.
 *
 * Shows the weekly schedule of an OJ Microline (WD5-series) thermostat from
 * its schedule sensor, highlighting the event that is active right now.
 * Tap a day to edit it; saving calls the ojmicroline_thermostat.set_schedule
 * action on the thermostat's climate entity. Bundled with and loaded by the
 * OJ Microline Thermostat integration.
 *
 *   type: custom:ojmicroline-schedule-card
 *   entity: sensor.bathroom_schedule
 *   title: Bathroom             # optional
 *   climate_entity: climate.x   # optional, found via the device otherwise
 */

const DOMAIN = "ojmicroline_thermostat";
const DAYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
];
const MAX_EVENTS = 6;
const DAY_SECONDS = 86400;
// 2024-01-01 was a Monday; used to get localized weekday names.
const MONDAY = Date.UTC(2024, 0, 1, 12);

const TEXTS = {
  en: {
    now: "Now",
    noSchedule: "No schedule",
    missing: "Entity not found",
    edit: "Edit",
    save: "Save",
    cancel: "Cancel",
    saving: "Saving…",
    add: "Add event",
    remove: "Remove",
    alsoApply: "Also apply to",
    nextDay: "next day",
    noClimate: "Thermostat not found; set climate_entity in the card.",
    hint: "Up to 6 events, on the quarter hour. A time earlier than the previous one is after midnight (03:00 at the latest).",
  },
  nl: {
    now: "Nu",
    noSchedule: "Geen schema",
    missing: "Entiteit niet gevonden",
    edit: "Bewerken",
    save: "Opslaan",
    cancel: "Annuleren",
    saving: "Opslaan…",
    add: "Moment toevoegen",
    remove: "Verwijderen",
    alsoApply: "Ook toepassen op",
    nextDay: "volgende dag",
    noClimate: "Thermostaat niet gevonden; stel climate_entity in op de kaart.",
    hint: "Tot 6 momenten, per kwartier. Een tijd vóór de vorige valt na middernacht (uiterlijk 03:00).",
  },
  pt: {
    now: "Agora",
    noSchedule: "Sem horário",
    missing: "Entidade não encontrada",
    edit: "Editar",
    save: "Guardar",
    cancel: "Cancelar",
    saving: "A guardar…",
    add: "Adicionar evento",
    remove: "Remover",
    alsoApply: "Aplicar também a",
    nextDay: "dia seguinte",
    noClimate: "Termóstato não encontrado; defina climate_entity no cartão.",
    hint: "Até 6 eventos, a cada quarto de hora. Uma hora anterior à anterior é depois da meia-noite (até às 03:00).",
  },
};

const escapeHtml = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );

const toSeconds = (event) => {
  const [hours, minutes] = event.time.split(":").map(Number);
  return hours * 3600 + minutes * 60 + (event.next_day ? DAY_SECONDS : 0);
};

const minutesOf = (time) => {
  const [hours, minutes] = time.split(":").map(Number);
  return hours * 60 + minutes;
};

const formatMinutes = (minutes) => {
  const value = ((minutes % 1440) + 1440) % 1440;
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
};

class OJMicrolineScheduleCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        {
          name: "entity",
          required: true,
          selector: { entity: { domain: "sensor", integration: DOMAIN } },
        },
        { name: "title", selector: { text: {} } },
        {
          name: "climate_entity",
          selector: { entity: { domain: "climate", integration: DOMAIN } },
        },
      ],
    };
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (entityId) =>
        entityId.startsWith("sensor.") &&
        entityId.endsWith("_schedule") &&
        Array.isArray(hass.states[entityId].attributes.monday),
    );
    return { entity: entity || "" };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Please define an entity");
    }
    this._config = config;
    this._draft = null;
    this._key = undefined;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // Never re-render while editing: it would reset the inputs.
    if (this._draft) return;
    // The highlighted event depends on the time, so also re-render when the
    // minute changes, not only when the sensor does.
    const state = hass.states[this._config.entity];
    const key = [
      state && state.last_updated,
      hass.locale && hass.locale.language,
      Math.floor(Date.now() / 60000),
    ].join("|");
    if (key !== this._key) {
      this._key = key;
      this._render();
    }
  }

  getCardSize() {
    return 5;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  connectedCallback() {
    this._timer = setInterval(() => {
      if (this._hass) this.hass = this._hass;
    }, 60000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  _language() {
    return (
      (this._hass &&
        ((this._hass.locale && this._hass.locale.language) || this._hass.language)) ||
      "en"
    );
  }

  _texts() {
    return TEXTS[this._language().split("-")[0]] || TEXTS.en;
  }

  _dayNames(weekday = "short") {
    const format = new Intl.DateTimeFormat(this._language(), {
      weekday,
      timeZone: "UTC",
    });
    return DAYS.map((_, index) =>
      format.format(new Date(MONDAY + index * DAY_SECONDS * 1000)),
    );
  }

  _formatTemperature(value) {
    return `${new Intl.NumberFormat(this._language(), { maximumFractionDigits: 1 }).format(value)}°`;
  }

  /** The climate entity to call set_schedule on. */
  _climateEntity() {
    if (this._config.climate_entity) return this._config.climate_entity;
    const entities = (this._hass && this._hass.entities) || {};
    const sensor = entities[this._config.entity];
    if (!sensor || !sensor.device_id) return undefined;
    return Object.keys(entities).find(
      (entityId) =>
        entityId.startsWith("climate.") &&
        entities[entityId].device_id === sensor.device_id,
    );
  }

  /** Return [dayIndex, eventIndex] of the event that is active now. */
  _activeEvent(schedule, now) {
    const today = (now.getDay() + 6) % 7;
    const yesterday = (today + 6) % 7;
    const nowSeconds = now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds();
    let active = null;
    let activeSeconds = -Infinity;
    for (const [day, offset] of [
      [yesterday, -DAY_SECONDS],
      [today, 0],
    ]) {
      (schedule[DAYS[day]] || []).forEach((event, index) => {
        const seconds = toSeconds(event) + offset;
        if (seconds <= nowSeconds && seconds >= activeSeconds) {
          active = [day, index];
          activeSeconds = seconds;
        }
      });
    }
    return active;
  }

  // --- Editing ---------------------------------------------------------

  _startEdit(dayIndex) {
    const state = this._hass.states[this._config.entity];
    const events = (state.attributes[DAYS[dayIndex]] || []).map((event) => ({
      time: event.time,
      temperature: event.temperature,
    }));
    this._draft = {
      day: dayIndex,
      events: events.length ? events : [{ time: "07:00", temperature: 20 }],
      days: new Set([dayIndex]),
      error: "",
      saving: false,
    };
    this._render();
  }

  _stopEdit() {
    this._draft = null;
    this._key = undefined;
    if (this._hass) this.hass = this._hass;
  }

  _addEvent() {
    const events = this._draft.events;
    if (events.length >= MAX_EVENTS) return;
    const last = events[events.length - 1];
    events.push({
      time: formatMinutes(Math.min(minutesOf(last.time) + 60, 23 * 60 + 45)),
      temperature: last.temperature,
    });
    this._render();
  }

  _removeEvent(index) {
    if (this._draft.events.length <= 1) return;
    this._draft.events.splice(index, 1);
    this._render();
  }

  async _save() {
    const draft = this._draft;
    const climate = this._climateEntity();
    if (!climate) {
      draft.error = this._texts().noClimate;
      this._render();
      return;
    }
    draft.saving = true;
    draft.error = "";
    this._render();
    try {
      await this._hass.callService(
        DOMAIN,
        "set_schedule",
        {
          days: DAYS.filter((_, index) => draft.days.has(index)),
          events: draft.events.map((event) => ({
            time: event.time,
            temperature: Number(event.temperature),
          })),
        },
        { entity_id: climate },
      );
      this._stopEdit();
    } catch (error) {
      draft.saving = false;
      draft.error = (error && error.message) || String(error);
      this._render();
    }
  }

  _onInput(event) {
    const target = event.target;
    const index = Number(target.dataset.index);
    if (target.dataset.field === "time") {
      this._draft.events[index].time = target.value;
      this._updateNextDayLabels();
    } else if (target.dataset.field === "temperature") {
      this._draft.events[index].temperature = target.value;
    } else if (target.dataset.field === "day") {
      if (target.checked) this._draft.days.add(index);
      else this._draft.days.delete(index);
    }
  }

  _nextDayFlags() {
    let previous = null;
    let nextDay = false;
    return this._draft.events.map((event) => {
      if (!event.time) return nextDay;
      const minutes = minutesOf(event.time);
      if (previous !== null && minutes < previous) nextDay = true;
      previous = minutes;
      return nextDay;
    });
  }

  _updateNextDayLabels() {
    const flags = this._nextDayFlags();
    this.shadowRoot.querySelectorAll(".next-day").forEach((label, index) => {
      label.hidden = !flags[index];
    });
  }

  // --- Rendering -------------------------------------------------------

  _render() {
    if (!this._config) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });

    const texts = this._texts();
    const state = this._hass && this._hass.states[this._config.entity];
    const title =
      this._config.title !== undefined
        ? this._config.title
        : state
          ? (state.attributes.friendly_name || "").replace(/ schedule$/i, "")
          : "";

    let current = "";
    let body = "";
    if (!this._hass) {
      body = "";
    } else if (!state) {
      body = `<div class="message">${escapeHtml(texts.missing)}: ${escapeHtml(this._config.entity)}</div>`;
    } else if (!Array.isArray(state.attributes.monday)) {
      body = `<div class="message">${escapeHtml(texts.noSchedule)}</div>`;
    } else if (this._draft) {
      body = this._editorHtml(texts);
    } else {
      const now = new Date();
      const active = this._activeEvent(state.attributes, now);
      if (active) {
        const temperature = state.attributes[DAYS[active[0]]][active[1]].temperature;
        current = `<div class="now">${escapeHtml(texts.now)}: <b>${escapeHtml(this._formatTemperature(temperature))}</b></div>`;
      }
      body = this._scheduleHtml(state.attributes, now, active, texts);
    }

    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <div class="title">${escapeHtml(title)}</div>
          ${current}
        </div>
        ${body}
      </ha-card>`;
    this._bind();
  }

  _scheduleHtml(schedule, now, active, texts) {
    const today = (now.getDay() + 6) % 7;
    const names = this._dayNames();
    const rows = DAYS.map((day, dayIndex) => {
      const events = (schedule[day] || [])
        .map((event, index) => {
          const isActive = active && active[0] === dayIndex && active[1] === index;
          return `<span class="event${isActive ? " active" : ""}">
            <span class="time">${escapeHtml(event.time)}${event.next_day ? "<sup>+1</sup>" : ""}</span>
            <span class="temp">${escapeHtml(this._formatTemperature(event.temperature))}</span>
          </span>`;
        })
        .join("");
      return `<button class="row${dayIndex === today ? " today" : ""}" data-action="edit" data-day="${dayIndex}"
          title="${escapeHtml(texts.edit)}">
        <span class="day">${escapeHtml(names[dayIndex])}</span>
        <span class="events">${events}</span>
        <span class="pencil" aria-hidden="true">✎</span>
      </button>`;
    }).join("");
    return `<div class="rows">${rows}</div>`;
  }

  _editorHtml(texts) {
    const draft = this._draft;
    const longNames = this._dayNames("long");
    const shortNames = this._dayNames();
    const flags = this._nextDayFlags();
    const rows = draft.events
      .map(
        (event, index) => `<div class="edit-row">
          <input type="time" step="900" data-field="time" data-index="${index}"
            value="${escapeHtml(event.time)}" ${draft.saving ? "disabled" : ""}>
          <span class="next-day" ${flags[index] ? "" : "hidden"}>${escapeHtml(texts.nextDay)}</span>
          <span class="spacer"></span>
          <input type="number" min="5" max="40" step="0.5" data-field="temperature" data-index="${index}"
            value="${escapeHtml(event.temperature)}" ${draft.saving ? "disabled" : ""}>
          <span class="unit">°C</span>
          <button class="icon" data-action="remove" data-index="${index}" title="${escapeHtml(texts.remove)}"
            ${draft.events.length <= 1 || draft.saving ? "disabled" : ""}>✕</button>
        </div>`,
      )
      .join("");
    const days = DAYS.map(
      (_, index) => `<label class="day-toggle">
        <input type="checkbox" data-field="day" data-index="${index}"
          ${draft.days.has(index) ? "checked" : ""} ${index === draft.day || draft.saving ? "disabled" : ""}>
        <span>${escapeHtml(shortNames[index])}</span>
      </label>`,
    ).join("");
    return `<div class="editor">
      <div class="editor-title">${escapeHtml(longNames[draft.day])}</div>
      ${rows}
      <button class="text" data-action="add"
        ${draft.events.length >= MAX_EVENTS || draft.saving ? "disabled" : ""}>+ ${escapeHtml(texts.add)}</button>
      <div class="hint">${escapeHtml(texts.hint)}</div>
      <div class="also">${escapeHtml(texts.alsoApply)}:</div>
      <div class="day-toggles">${days}</div>
      ${draft.error ? `<div class="error">${escapeHtml(draft.error)}</div>` : ""}
      <div class="actions">
        <button class="text" data-action="cancel" ${draft.saving ? "disabled" : ""}>${escapeHtml(texts.cancel)}</button>
        <button class="primary" data-action="save" ${draft.saving ? "disabled" : ""}>
          ${escapeHtml(draft.saving ? texts.saving : texts.save)}</button>
      </div>
    </div>`;
  }

  _bind() {
    const root = this.shadowRoot;
    const title = root.querySelector(".title");
    if (title) {
      title.onclick = () =>
        this.dispatchEvent(
          new CustomEvent("hass-more-info", {
            detail: { entityId: this._config.entity },
            bubbles: true,
            composed: true,
          }),
        );
    }
    root.querySelectorAll("[data-action]").forEach((element) => {
      element.onclick = (event) => {
        event.stopPropagation();
        const { action, day, index } = element.dataset;
        if (action === "edit") this._startEdit(Number(day));
        else if (action === "add") this._addEvent();
        else if (action === "remove") this._removeEvent(Number(index));
        else if (action === "cancel") this._stopEdit();
        else if (action === "save") this._save();
      };
    });
    root.querySelectorAll("input[data-field]").forEach((input) => {
      input.oninput = (event) => this._onInput(event);
      input.onchange = (event) => this._onInput(event);
    });
  }
}

const STYLE = `
  ha-card { padding: 16px; }
  .header { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin-bottom: 12px; }
  .title { font-size: 1.2em; font-weight: 500; color: var(--primary-text-color); cursor: pointer; }
  .now { color: var(--secondary-text-color); white-space: nowrap; }
  .now b { color: var(--primary-text-color); }
  .rows { display: flex; flex-direction: column; gap: 4px; }
  .row { display: flex; align-items: center; gap: 8px; padding: 4px 6px; border-radius: 8px;
    border: none; background: none; font: inherit; color: inherit; text-align: left; cursor: pointer; width: 100%; }
  .row:hover, .row:focus-visible { background: var(--secondary-background-color); outline: none; }
  .row.today { background: var(--secondary-background-color); }
  .day { width: 2.8em; flex: none; color: var(--secondary-text-color); text-transform: capitalize; }
  .row.today .day { color: var(--primary-text-color); font-weight: 500; }
  .events { display: flex; flex-wrap: wrap; gap: 4px; flex: 1; }
  .pencil { color: var(--secondary-text-color); opacity: 0; transition: opacity .15s; }
  .row:hover .pencil, .row:focus-visible .pencil { opacity: 1; }
  .event { display: inline-flex; gap: 4px; padding: 2px 8px; border-radius: 12px;
    border: 1px solid var(--divider-color); font-size: 0.9em; line-height: 1.6; }
  .event .time { color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .event .temp { color: var(--primary-text-color); font-weight: 500; }
  .event.active { background: var(--primary-color); border-color: var(--primary-color); }
  .event.active .time, .event.active .temp { color: var(--text-primary-color, #fff); }
  sup { font-size: 0.7em; }
  .message { color: var(--secondary-text-color); }
  .editor { display: flex; flex-direction: column; gap: 8px; }
  .editor-title { font-weight: 500; color: var(--primary-text-color); text-transform: capitalize; }
  .edit-row { display: flex; align-items: center; gap: 8px; }
  .spacer { flex: 1; }
  .next-day { font-size: 0.8em; color: var(--secondary-text-color); }
  .unit { color: var(--secondary-text-color); }
  input[type=time], input[type=number] { font: inherit; color: var(--primary-text-color);
    background: var(--secondary-background-color); border: 1px solid var(--divider-color);
    border-radius: 6px; padding: 4px 6px; }
  input[type=number] { width: 4.5em; }
  button { font: inherit; cursor: pointer; }
  button:disabled { cursor: default; opacity: .5; }
  button.icon { border: none; background: none; color: var(--secondary-text-color); padding: 4px 6px; border-radius: 6px; }
  button.icon:hover:not(:disabled) { background: var(--secondary-background-color); }
  button.text { align-self: flex-start; border: none; background: none; color: var(--primary-color); padding: 4px 0; }
  button.primary { border: none; border-radius: 6px; padding: 6px 16px;
    background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .hint, .also { font-size: 0.85em; color: var(--secondary-text-color); }
  .day-toggles { display: flex; flex-wrap: wrap; gap: 4px 12px; }
  .day-toggle { display: inline-flex; align-items: center; gap: 4px; text-transform: capitalize;
    color: var(--primary-text-color); }
  .error { color: var(--error-color, #db4437); font-size: 0.9em; }
  .actions { display: flex; justify-content: flex-end; align-items: center; gap: 16px; }
`;

if (!customElements.get("ojmicroline-schedule-card")) {
  customElements.define("ojmicroline-schedule-card", OJMicrolineScheduleCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "ojmicroline-schedule-card",
    name: "OJ Microline schedule",
    description: "The weekly schedule of an OJ Microline thermostat, editable per day.",
    preview: true,
    documentationURL:
      "https://github.com/robbinjanssen/home-assistant-ojmicroline-thermostat",
  });
}

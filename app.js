(() => {
  "use strict";

  const dataset = window.CONFERENCE_DATA;
  if (!dataset || !Array.isArray(dataset.conferences)) {
    document.body.innerHTML = '<p style="padding:2rem">data.js를 불러오지 못했습니다.</p>';
    return;
  }

  const DAY_MS = 86_400_000;
  const zoomLevels = [1.35, 1.8, 2.35, 3.0, 3.8];
  const fieldLabels = {
    abstract: "초록 등록",
    submission: "논문 제출",
    notification: "결과 발표",
    cameraReady: "최종본",
    conferenceStart: "학회 시작",
    conferenceEnd: "학회 종료"
  };

  function readStoredTheme() {
    try {
      return localStorage.getItem("cfp-theme") || "light";
    } catch {
      return "light";
    }
  }

  const state = {
    query: "",
    sort: "deadline",
    hidePast: false,
    within90Days: false,
    zoomIndex: 2,
    theme: readStoredTheme()
  };

  const els = {
    conferenceCount: document.getElementById("conferenceCount"),
    searchInput: document.getElementById("searchInput"),
    sortSelect: document.getElementById("sortSelect"),
    hidePastInput: document.getElementById("hidePastInput"),
    zoomOutButton: document.getElementById("zoomOutButton"),
    zoomInButton: document.getElementById("zoomInButton"),
    zoomOutput: document.getElementById("zoomOutput"),
    todayButton: document.getElementById("todayButton"),
    themeButton: document.getElementById("themeButton"),
    timelineScroll: document.getElementById("timelineScroll"),
    timelineTable: document.getElementById("timelineTable"),
    timelineStatus: document.getElementById("timelineStatus"),
    nextDeadlineName: document.getElementById("nextDeadlineName"),
    nextDeadlineDate: document.getElementById("nextDeadlineDate"),
    deadline90Count: document.getElementById("deadline90Count"),
    deadline90FilterButton: document.getElementById("deadline90FilterButton"),
    visibleCount: document.getElementById("visibleCount"),
    dataUpdated: document.getElementById("dataUpdated"),
    dataNote: document.getElementById("dataNote"),
    detailDialog: document.getElementById("detailDialog"),
    dialogContent: document.getElementById("dialogContent"),
    dialogCloseButton: document.getElementById("dialogCloseButton"),
    tooltip: document.getElementById("tooltip"),
    toast: document.getElementById("toast")
  };

  const dateFields = Object.keys(fieldLabels);
  const allDates = dataset.conferences.flatMap((conference) =>
    conference.editions.flatMap((edition) =>
      dateFields.map((field) => edition[field]).filter(Boolean).map(parseDate)
    )
  );

  const rangeStart = startOfMonth(addDays(new Date(Math.min(...allDates.map(Number))), -45));
  const rangeEnd = endOfMonth(addDays(new Date(Math.max(...allDates.map(Number))), 45));
  const totalDays = diffDays(rangeStart, rangeEnd) + 1;

  function parseDate(value) {
    const [year, month, day] = value.split("-").map(Number);
    return new Date(Date.UTC(year, month - 1, day));
  }

  function todayUtc() {
    const now = new Date();
    return new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  }

  function addDays(date, days) {
    return new Date(date.getTime() + days * DAY_MS);
  }

  function diffDays(a, b) {
    return Math.round((b.getTime() - a.getTime()) / DAY_MS);
  }

  function startOfMonth(date) {
    return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1));
  }

  function endOfMonth(date) {
    return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0));
  }

  function formatDate(dateOrString, options = {}) {
    const date = typeof dateOrString === "string" ? parseDate(dateOrString) : dateOrString;
    return new Intl.DateTimeFormat("ko-KR", {
      timeZone: "UTC",
      year: options.noYear ? undefined : "numeric",
      month: options.short ? "short" : "long",
      day: "numeric",
      weekday: options.weekday ? "short" : undefined
    }).format(date);
  }

  function formatCompact(dateOrString) {
    const date = typeof dateOrString === "string" ? parseDate(dateOrString) : dateOrString;
    return new Intl.DateTimeFormat("ko-KR", {
      timeZone: "UTC",
      year: "numeric",
      month: "2-digit",
      day: "2-digit"
    }).format(date).replace(/\. /g, ".").replace(/\.$/, "");
  }

  function dateToX(dateOrString, pxPerDay = zoomLevels[state.zoomIndex]) {
    const date = typeof dateOrString === "string" ? parseDate(dateOrString) : dateOrString;
    return diffDays(rangeStart, date) * pxPerDay;
  }

  function xToDate(x, pxPerDay = zoomLevels[state.zoomIndex]) {
    return addDays(rangeStart, Math.round(x / pxPerDay));
  }

  function isEstimated(edition, ...fields) {
    return fields.some((field) => edition.estimated?.includes(field));
  }

  function editionLastDate(edition) {
    const values = dateFields.map((field) => edition[field]).filter(Boolean).map(parseDate);
    return new Date(Math.max(...values.map(Number)));
  }

  function editionFirstDate(edition) {
    const values = dateFields.map((field) => edition[field]).filter(Boolean).map(parseDate);
    return new Date(Math.min(...values.map(Number)));
  }

  function getUpcomingSubmission(conference, after = todayUtc()) {
    return conference.editions
      .filter((edition) => edition.submission && parseDate(edition.submission) >= after)
      .map((edition) => ({ conference, edition, date: parseDate(edition.submission) }))
      .sort((a, b) => a.date - b.date)[0] || null;
  }

  function getUpcomingConference(conference, after = todayUtc()) {
    return conference.editions
      .filter((edition) => edition.conferenceStart && parseDate(edition.conferenceStart) >= after)
      .map((edition) => ({ conference, edition, date: parseDate(edition.conferenceStart) }))
      .sort((a, b) => a.date - b.date)[0] || null;
  }

  function getFilteredEditions(conference) {
    if (!state.hidePast) return conference.editions;
    const today = todayUtc();
    return conference.editions.filter((edition) => editionLastDate(edition) >= today);
  }

  function hasSubmissionWithinDays(conference, days) {
    const today = todayUtc();
    return conference.editions.some((edition) => {
      if (!edition.submission) return false;
      const remaining = diffDays(today, parseDate(edition.submission));
      return remaining >= 0 && remaining <= days;
    });
  }

  function getVisibleConferences() {
    const query = state.query.trim().toLowerCase();
    let conferences = dataset.conferences
      .filter((conference) => {
        const matchesQuery = !query || `${conference.acronym} ${conference.name}`.toLowerCase().includes(query);
        const matchesDeadlineWindow = !state.within90Days || hasSubmissionWithinDays(conference, 90);
        return matchesQuery && matchesDeadlineWindow && getFilteredEditions(conference).length > 0;
      })
      .slice();

    const infinity = Number.POSITIVE_INFINITY;
    conferences.sort((a, b) => {
      if (state.sort === "acronym") return a.acronym.localeCompare(b.acronym);
      if (state.sort === "conference") {
        const aDate = getUpcomingConference(a)?.date.getTime() ?? infinity;
        const bDate = getUpcomingConference(b)?.date.getTime() ?? infinity;
        return aDate - bDate || a.acronym.localeCompare(b.acronym);
      }
      const aDate = getUpcomingSubmission(a)?.date.getTime() ?? infinity;
      const bDate = getUpcomingSubmission(b)?.date.getTime() ?? infinity;
      return aDate - bDate || a.acronym.localeCompare(b.acronym);
    });
    return conferences;
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function render() {
    const pxPerDay = zoomLevels[state.zoomIndex];
    const timelineWidth = Math.ceil(totalDays * pxPerDay);
    const visible = getVisibleConferences();

    document.documentElement.style.setProperty("--timeline-width", `${timelineWidth}px`);
    document.documentElement.dataset.theme = state.theme;
    els.zoomOutput.value = `${Math.round((pxPerDay / zoomLevels[2]) * 100)}%`;
    els.zoomOutButton.disabled = state.zoomIndex === 0;
    els.zoomInButton.disabled = state.zoomIndex === zoomLevels.length - 1;
    els.themeButton.textContent = state.theme === "dark" ? "☀" : "◐";
    els.themeButton.setAttribute("aria-label", state.theme === "dark" ? "라이트 모드 전환" : "다크 모드 전환");

    els.timelineTable.innerHTML = "";
    els.timelineTable.appendChild(renderHeader(timelineWidth, pxPerDay));

    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "no-results";
      empty.innerHTML = '<div><strong>표시할 학회가 없습니다.</strong><span>검색어 또는 지난 일정 숨기기 설정을 바꿔보세요.</span></div>';
      empty.style.width = `calc(var(--label-width) + ${timelineWidth}px)`;
      els.timelineTable.appendChild(empty);
      els.timelineStatus.textContent = "검색 결과 없음";
    } else {
      visible.forEach((conference) => els.timelineTable.appendChild(renderConferenceRow(conference, pxPerDay)));
      const activeFilters = [];
      if (state.within90Days) activeFilters.push("90일 이내 마감");
      if (state.query) activeFilters.push(`“${state.query}” 검색`);
      els.timelineStatus.textContent = activeFilters.length ? `${activeFilters.join(" · ")} 결과 ${visible.length}개 학회` : "";
    }

    renderTodayLine(pxPerDay);
    updateSummary(visible);
    attachInteractiveHandlers();
  }

  function renderHeader(timelineWidth, pxPerDay) {
    const header = document.createElement("div");
    header.className = "timeline-header";

    const corner = document.createElement("div");
    corner.className = "timeline-corner";
    corner.textContent = "Conference";

    const dateHeader = document.createElement("div");
    dateHeader.className = "date-header";
    dateHeader.style.width = `${timelineWidth}px`;

    const today = todayUtc();
    let cursor = startOfMonth(rangeStart);
    const yearStarts = new Map();
    while (cursor <= rangeEnd) {
      const nextMonth = new Date(Date.UTC(cursor.getUTCFullYear(), cursor.getUTCMonth() + 1, 1));
      const left = dateToX(cursor, pxPerDay);
      const right = Math.min(timelineWidth, dateToX(nextMonth, pxPerDay));
      const month = document.createElement("div");
      month.className = "month-cell";
      if (cursor.getUTCFullYear() === today.getUTCFullYear() && cursor.getUTCMonth() === today.getUTCMonth()) {
        month.classList.add("current-month");
      }
      month.style.left = `${left}px`;
      month.style.width = `${Math.max(0, right - left)}px`;
      month.textContent = new Intl.DateTimeFormat("ko-KR", { timeZone: "UTC", month: "short" }).format(cursor);
      dateHeader.appendChild(month);

      if (!yearStarts.has(cursor.getUTCFullYear())) yearStarts.set(cursor.getUTCFullYear(), cursor);
      cursor = nextMonth;
    }

    [...yearStarts.entries()].forEach(([year, start], index, entries) => {
      const nextStart = entries[index + 1]?.[1] || addDays(rangeEnd, 1);
      const left = dateToX(start < rangeStart ? rangeStart : start, pxPerDay);
      const right = Math.min(timelineWidth, dateToX(nextStart, pxPerDay));
      const cell = document.createElement("div");
      cell.className = "year-cell";
      cell.style.left = `${Math.max(0, left)}px`;
      cell.style.width = `${Math.max(0, right - Math.max(0, left))}px`;
      cell.textContent = String(year);
      dateHeader.appendChild(cell);
    });

    header.append(corner, dateHeader);
    return header;
  }

  function renderConferenceRow(conference, pxPerDay) {
    const editions = getFilteredEditions(conference);
    const rowHeight = Math.max(72, editions.length * 44 + 20);
    const row = document.createElement("div");
    row.className = "conference-row";
    row.style.height = `${rowHeight}px`;
    row.dataset.conference = conference.acronym;

    const label = document.createElement("div");
    label.className = "conference-label";
    label.tabIndex = 0;
    label.setAttribute("role", "button");
    label.setAttribute("aria-label", `${conference.acronym} 상세 일정 열기`);

    const upcoming = getUpcomingSubmission(conference);
    const days = upcoming ? diffDays(todayUtc(), upcoming.date) : null;
    const chip = upcoming
      ? `<span class="next-chip">D-${days}<br>${formatCompact(upcoming.date).slice(5)}</span>`
      : '<span class="next-chip">마감<br>미정</span>';

    label.innerHTML = `
      <div class="conference-label-main">
        <div class="acronym"><span class="status-dot"></span>${escapeHtml(conference.acronym)}</div>
        <div class="full-name">${escapeHtml(conference.name)}</div>
      </div>
      ${chip}
    `;
    label.addEventListener("click", () => openDetails(conference));
    label.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openDetails(conference);
      }
    });

    const lane = document.createElement("div");
    lane.className = "timeline-lane";
    lane.style.height = `${rowHeight}px`;
    lane.style.width = `${Math.ceil(totalDays * pxPerDay)}px`;
    renderMonthGrid(lane, pxPerDay);

    editions.forEach((edition, editionIndex) => {
      const baseTop = 18 + editionIndex * 44;
      if (editionIndex > 0) {
        const separator = document.createElement("div");
        separator.className = "edition-line";
        separator.style.top = `${editionIndex * 44 + 8}px`;
        lane.appendChild(separator);
      }
      renderEditionItems(lane, conference, edition, baseTop, pxPerDay);
    });

    row.append(label, lane);
    return row;
  }

  function renderMonthGrid(lane, pxPerDay) {
    let cursor = startOfMonth(rangeStart);
    while (cursor <= rangeEnd) {
      const line = document.createElement("span");
      line.className = "month-grid-line";
      line.style.cssText = `position:absolute;top:0;bottom:0;left:${dateToX(cursor, pxPerDay)}px;width:1px;background:var(--line);opacity:.55;pointer-events:none;`;
      lane.appendChild(line);
      cursor = new Date(Date.UTC(cursor.getUTCFullYear(), cursor.getUTCMonth() + 1, 1));
    }
  }

  function renderEditionItems(lane, conference, edition, top, pxPerDay) {
    const sourceLabel = `${conference.acronym} ${edition.year}`;

    if (edition.abstract && edition.submission) {
      appendRange(lane, {
        type: "presub",
        start: edition.abstract,
        end: edition.submission,
        top: top + 12,
        estimated: isEstimated(edition, "abstract", "submission"),
        tooltip: tooltipHtml(sourceLabel, "초록 등록 → 논문 제출", edition.abstract, edition.submission, isEstimated(edition, "abstract", "submission")),
        onClick: () => openDetails(conference, edition.year)
      }, pxPerDay);
      appendMarker(lane, "abstract", edition.abstract, top + 8, tooltipHtml(sourceLabel, "초록 등록", edition.abstract, null, isEstimated(edition, "abstract")), () => openDetails(conference, edition.year), pxPerDay, isEstimated(edition, "abstract"));
    }

    if (edition.submission && edition.notification) {
      appendRange(lane, {
        type: "review",
        start: edition.submission,
        end: edition.notification,
        top: top + 8,
        estimated: isEstimated(edition, "submission", "notification"),
        tooltip: tooltipHtml(sourceLabel, "심사 기간", edition.submission, edition.notification, isEstimated(edition, "submission", "notification")),
        onClick: () => openDetails(conference, edition.year)
      }, pxPerDay);
      appendMarker(lane, "notification", edition.notification, top + 9, tooltipHtml(sourceLabel, "결과 발표", edition.notification, null, isEstimated(edition, "notification")), () => openDetails(conference, edition.year), pxPerDay, isEstimated(edition, "notification"));
    }

    if (edition.submission) {
      appendMarker(lane, "submission", edition.submission, top + 8, tooltipHtml(sourceLabel, "논문 제출", edition.submission, null, isEstimated(edition, "submission")), () => openDetails(conference, edition.year), pxPerDay, isEstimated(edition, "submission"));
    }

    if (edition.cameraReady) {
      appendMarker(lane, "camera", edition.cameraReady, top + 8, tooltipHtml(sourceLabel, "최종본 제출", edition.cameraReady, null, isEstimated(edition, "cameraReady")), () => openDetails(conference, edition.year), pxPerDay, isEstimated(edition, "cameraReady"));
    }

    if (edition.conferenceStart && edition.conferenceEnd) {
      appendRange(lane, {
        type: "conference",
        start: edition.conferenceStart,
        end: edition.conferenceEnd,
        top: top + 6,
        estimated: isEstimated(edition, "conferenceStart", "conferenceEnd"),
        tooltip: tooltipHtml(sourceLabel, "학회 개최", edition.conferenceStart, edition.conferenceEnd, isEstimated(edition, "conferenceStart", "conferenceEnd")),
        onClick: () => openDetails(conference, edition.year)
      }, pxPerDay);
      const label = document.createElement("span");
      label.className = "track-label";
      label.style.left = `${dateToX(edition.conferenceStart, pxPerDay) + 7}px`;
      label.style.top = `${top - 10}px`;
      label.innerHTML = `${escapeHtml(conference.acronym)} <span class="track-year">${edition.year}</span>`;
      lane.appendChild(label);
    } else {
      const label = document.createElement("span");
      label.className = "track-label";
      label.style.left = `${Math.max(4, dateToX(editionFirstDate(edition), pxPerDay) - 2)}px`;
      label.style.top = `${top - 10}px`;
      label.innerHTML = `${escapeHtml(conference.acronym)} <span class="track-year">${edition.year}</span>`;
      lane.appendChild(label);
    }
  }

  function appendRange(lane, config, pxPerDay) {
    const item = document.createElement("div");
    item.className = `timeline-item range-bar ${config.type}${config.estimated ? " estimated" : ""}`;
    const left = dateToX(config.start, pxPerDay);
    const end = dateToX(config.end, pxPerDay) + pxPerDay;
    item.style.left = `${left}px`;
    item.style.width = `${Math.max(config.type === "conference" ? 8 : 5, end - left)}px`;
    item.style.top = `${config.top}px`;
    item.dataset.tooltip = config.tooltip;
    item.tabIndex = 0;
    item.setAttribute("role", "button");
    item.addEventListener("click", config.onClick);
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        config.onClick();
      }
    });
    lane.appendChild(item);
  }

  function appendMarker(lane, type, date, top, tooltip, onClick, pxPerDay, estimated) {
    const marker = document.createElement("div");
    marker.className = `timeline-item marker ${type}${estimated ? " estimated" : ""}`;
    marker.style.left = `${dateToX(date, pxPerDay)}px`;
    marker.style.top = `${top}px`;
    marker.dataset.tooltip = tooltip;
    marker.tabIndex = 0;
    marker.setAttribute("role", "button");
    marker.addEventListener("click", onClick);
    marker.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onClick();
      }
    });
    lane.appendChild(marker);
  }

  function tooltipHtml(title, type, start, end, estimated) {
    const dateText = end && end !== start
      ? `${formatDate(start, { short: true, weekday: true })} – ${formatDate(end, { short: true, weekday: true })}`
      : formatDate(start, { short: true, weekday: true });
    return `<strong>${escapeHtml(title)} · ${escapeHtml(type)}</strong>${escapeHtml(dateText)}${estimated ? "<small>과거 주기 기반 추정 일정</small>" : ""}`;
  }

  function renderTodayLine(pxPerDay) {
    const today = todayUtc();
    if (today < rangeStart || today > rangeEnd) return;
    const line = document.createElement("div");
    line.className = "today-line";
    line.style.left = `calc(var(--label-width) + ${dateToX(today, pxPerDay)}px)`;
    els.timelineTable.appendChild(line);
  }

  function updateSummary(visible) {
    const today = todayUtc();
    const upcoming = dataset.conferences
      .flatMap((conference) => conference.editions
        .filter((edition) => edition.submission && parseDate(edition.submission) >= today)
        .map((edition) => ({ conference, edition, date: parseDate(edition.submission) })))
      .sort((a, b) => a.date - b.date);

    if (upcoming[0]) {
      const days = diffDays(today, upcoming[0].date);
      els.nextDeadlineName.textContent = `${upcoming[0].conference.acronym} ${upcoming[0].edition.year}`;
      els.nextDeadlineDate.textContent = `${formatDate(upcoming[0].date, { short: true, weekday: true })} · D-${days}`;
    } else {
      els.nextDeadlineName.textContent = "등록된 마감 없음";
      els.nextDeadlineDate.textContent = "data.js에서 일정을 추가하세요";
    }

    els.deadline90Count.textContent = String(upcoming.filter((item) => diffDays(today, item.date) <= 90).length);
    els.deadline90FilterButton.classList.toggle("active", state.within90Days);
    els.deadline90FilterButton.setAttribute("aria-pressed", String(state.within90Days));
    els.deadline90FilterButton.title = state.within90Days
      ? "90일 이내 마감 필터 해제"
      : "90일 이내 논문 마감이 있는 학회만 표시";
    els.visibleCount.textContent = String(visible.length);
    els.dataUpdated.textContent = formatCompact(dataset.updated);
    els.conferenceCount.textContent = `${dataset.conferences.length} conferences`;
    els.dataNote.textContent = dataset.sourceNote;
  }

  function attachInteractiveHandlers() {
    document.querySelectorAll("[data-tooltip]").forEach((element) => {
      element.addEventListener("pointerenter", showTooltip);
      element.addEventListener("pointermove", moveTooltip);
      element.addEventListener("pointerleave", hideTooltip);
      element.addEventListener("focus", showTooltipFromFocus);
      element.addEventListener("blur", hideTooltip);
    });
  }

  function showTooltip(event) {
    els.tooltip.innerHTML = event.currentTarget.dataset.tooltip;
    els.tooltip.hidden = false;
    moveTooltip(event);
  }

  function moveTooltip(event) {
    const padding = 16;
    const rect = els.tooltip.getBoundingClientRect();
    let x = event.clientX + 12;
    let y = event.clientY + 12;
    if (x + rect.width > window.innerWidth - padding) x = event.clientX - rect.width - 12;
    if (y + rect.height > window.innerHeight - padding) y = event.clientY - rect.height - 12;
    els.tooltip.style.left = `${Math.max(padding, x)}px`;
    els.tooltip.style.top = `${Math.max(padding, y)}px`;
    els.tooltip.style.transform = "none";
  }

  function showTooltipFromFocus(event) {
    els.tooltip.innerHTML = event.currentTarget.dataset.tooltip;
    els.tooltip.hidden = false;
    const rect = event.currentTarget.getBoundingClientRect();
    els.tooltip.style.left = `${Math.min(window.innerWidth - 290, rect.left + rect.width + 8)}px`;
    els.tooltip.style.top = `${Math.min(window.innerHeight - 100, rect.top)}px`;
    els.tooltip.style.transform = "none";
  }

  function hideTooltip() {
    els.tooltip.hidden = true;
  }

  function openDetails(conference, highlightYear = null) {
    const cards = conference.editions.map((edition) => {
      const fields = ["abstract", "submission", "notification", "cameraReady", "conferenceStart", "conferenceEnd"];
      const dates = fields
        .filter((field) => edition[field])
        .map((field) => `
          <div class="${isEstimated(edition, field) ? "estimated-date" : ""}">
            <dt>${fieldLabels[field]}</dt>
            <dd>${escapeHtml(formatDate(edition[field], { short: true, weekday: true }))}</dd>
          </div>
        `).join("");
      const hasEstimate = Boolean(edition.estimated?.length);
      return `
        <article class="edition-card" data-year="${edition.year}"${highlightYear === edition.year ? ' style="border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)"' : ""}>
          <div class="edition-card-head">
            <strong>${escapeHtml(conference.acronym)} ${edition.year}</strong>
            ${hasEstimate ? '<span class="estimate-badge">일부 추정</span>' : ""}
          </div>
          <p class="edition-location${edition.location === "미정" ? " pending" : ""}">
            <span class="location-icon" aria-hidden="true">⌖</span>
            <span>${escapeHtml(edition.location || "미정")}</span>
          </p>
          <dl class="date-list">${dates}</dl>
          <div class="edition-footer">
            <button type="button" data-ics-conference="${escapeHtml(conference.acronym)}" data-ics-year="${edition.year}">ICS 저장</button>
            <a href="${escapeHtml(edition.source || conference.homepage)}" target="_blank" rel="noopener noreferrer">일정 출처 ↗</a>
          </div>
        </article>
      `;
    }).join("");

    els.dialogContent.innerHTML = `
      <header class="dialog-header">
        <p class="dialog-acronym">${escapeHtml(conference.acronym)}</p>
        <h3>${escapeHtml(conference.name)}</h3>
        <p>${conference.editions.length}개 연도 일정 · 추정 날짜는 별도로 표시됩니다.</p>
        <div class="dialog-actions">
          <a href="${escapeHtml(conference.homepage)}" target="_blank" rel="noopener noreferrer">공식 홈페이지 ↗</a>
          <button type="button" data-copy-link="${escapeHtml(conference.homepage)}">홈페이지 주소 복사</button>
        </div>
      </header>
      <div class="edition-cards">${cards}</div>
    `;

    els.dialogContent.querySelectorAll("[data-ics-conference]").forEach((button) => {
      button.addEventListener("click", () => {
        const year = Number(button.dataset.icsYear);
        const edition = conference.editions.find((item) => item.year === year);
        downloadIcs(conference, edition);
      });
    });
    els.dialogContent.querySelector("[data-copy-link]")?.addEventListener("click", async (event) => {
      try {
        await navigator.clipboard.writeText(event.currentTarget.dataset.copyLink);
        showToast("홈페이지 주소를 복사했습니다.");
      } catch {
        showToast("주소 복사가 지원되지 않는 환경입니다.");
      }
    });

    els.detailDialog.showModal();
    requestAnimationFrame(() => {
      if (highlightYear) {
        els.dialogContent.querySelector(`[data-year="${highlightYear}"]`)?.scrollIntoView({ block: "center" });
      }
    });
  }

  function escapeIcs(value) {
    return String(value).replaceAll("\\", "\\\\").replaceAll(";", "\\;").replaceAll(",", "\\,").replaceAll("\n", "\\n");
  }

  function icsDate(value) {
    return value.replaceAll("-", "");
  }

  function downloadIcs(conference, edition) {
    const events = [];
    const addAllDay = (date, summary, description = "") => {
      const end = addDays(parseDate(date), 1);
      events.push([
        "BEGIN:VEVENT",
        `UID:${conference.acronym}-${edition.year}-${summary.replaceAll(" ", "-")}@cg-conference-timeline`,
        `DTSTAMP:${new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "")}`,
        `DTSTART;VALUE=DATE:${icsDate(date)}`,
        `DTEND;VALUE=DATE:${icsDate(end.toISOString().slice(0, 10))}`,
        `SUMMARY:${escapeIcs(summary)}`,
        `DESCRIPTION:${escapeIcs(description)}`,
        `URL:${escapeIcs(edition.source || conference.homepage)}`,
        "END:VEVENT"
      ].join("\r\n"));
    };

    if (edition.abstract) addAllDay(edition.abstract, `${conference.acronym} ${edition.year} 초록 마감`, conference.name);
    if (edition.submission) addAllDay(edition.submission, `${conference.acronym} ${edition.year} 논문 마감`, conference.name);
    if (edition.notification) addAllDay(edition.notification, `${conference.acronym} ${edition.year} 결과 발표`, conference.name);
    if (edition.cameraReady) addAllDay(edition.cameraReady, `${conference.acronym} ${edition.year} 최종본 마감`, conference.name);
    if (edition.conferenceStart && edition.conferenceEnd) {
      const conferenceEndExclusive = addDays(parseDate(edition.conferenceEnd), 1).toISOString().slice(0, 10);
      events.push([
        "BEGIN:VEVENT",
        `UID:${conference.acronym}-${edition.year}-conference@cg-conference-timeline`,
        `DTSTAMP:${new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "")}`,
        `DTSTART;VALUE=DATE:${icsDate(edition.conferenceStart)}`,
        `DTEND;VALUE=DATE:${icsDate(conferenceEndExclusive)}`,
        `SUMMARY:${escapeIcs(`${conference.acronym} ${edition.year}`)}`,
        `DESCRIPTION:${escapeIcs(conference.name)}`,
        ...(edition.location && edition.location !== "미정" ? [`LOCATION:${escapeIcs(edition.location)}`] : []),
        `URL:${escapeIcs(edition.source || conference.homepage)}`,
        "END:VEVENT"
      ].join("\r\n"));
    }

    const ics = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CG Conference Timeline//KO", "CALSCALE:GREGORIAN", ...events, "END:VCALENDAR"].join("\r\n");
    const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${conference.acronym}-${edition.year}.ics`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    showToast(`${conference.acronym} ${edition.year} 일정을 저장했습니다.`);
  }

  let toastTimer;
  function showToast(message) {
    clearTimeout(toastTimer);
    els.toast.textContent = message;
    els.toast.classList.add("show");
    toastTimer = setTimeout(() => els.toast.classList.remove("show"), 2200);
  }

  function scrollToToday(behavior = "smooth") {
    const labelWidth = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--label-width")) || 258;
    const target = labelWidth + dateToX(todayUtc()) - els.timelineScroll.clientWidth / 2;
    els.timelineScroll.scrollTo({ left: Math.max(0, target), behavior });
  }

  function changeZoom(direction) {
    const oldPx = zoomLevels[state.zoomIndex];
    const labelWidth = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--label-width")) || 258;
    const centerTimelineX = Math.max(0, els.timelineScroll.scrollLeft + els.timelineScroll.clientWidth / 2 - labelWidth);
    const centerDate = xToDate(centerTimelineX, oldPx);
    state.zoomIndex = Math.max(0, Math.min(zoomLevels.length - 1, state.zoomIndex + direction));
    render();
    const newTarget = labelWidth + dateToX(centerDate) - els.timelineScroll.clientWidth / 2;
    els.timelineScroll.scrollLeft = Math.max(0, newTarget);
  }

  els.searchInput.addEventListener("input", (event) => {
    state.query = event.target.value;
    render();
  });
  els.deadline90FilterButton.addEventListener("click", () => {
    state.within90Days = !state.within90Days;
    if (state.within90Days) {
      state.query = "";
      state.sort = "deadline";
      els.searchInput.value = "";
      els.sortSelect.value = "deadline";
      showToast("90일 이내 논문 마감이 있는 학회만 표시합니다.");
    } else {
      showToast("90일 이내 마감 필터를 해제했습니다.");
    }
    render();
    requestAnimationFrame(() => scrollToToday("smooth"));
  });
  els.sortSelect.addEventListener("change", (event) => {
    state.sort = event.target.value;
    render();
  });
  els.hidePastInput.addEventListener("change", (event) => {
    state.hidePast = event.target.checked;
    render();
  });
  els.zoomOutButton.addEventListener("click", () => changeZoom(-1));
  els.zoomInButton.addEventListener("click", () => changeZoom(1));
  els.todayButton.addEventListener("click", () => scrollToToday());
  els.themeButton.addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    try {
      localStorage.setItem("cfp-theme", state.theme);
    } catch {
      // Storage may be unavailable in strict privacy or embedded contexts.
    }
    render();
  });
  els.dialogCloseButton.addEventListener("click", () => els.detailDialog.close());
  els.detailDialog.addEventListener("click", (event) => {
    if (event.target === els.detailDialog) els.detailDialog.close();
  });
  window.addEventListener("keydown", (event) => {
    const tag = document.activeElement?.tagName;
    if (event.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(tag)) {
      event.preventDefault();
      els.searchInput.focus();
    }
  });

  render();
  requestAnimationFrame(() => scrollToToday("auto"));
})();

(function () {
  const legsRoot = document.getElementById("bet-legs");
  const kindSelect = document.getElementById("bet-kind");
  const addButton = document.getElementById("add-leg");
  const form = document.getElementById("bet-form");
  if (!form || !legsRoot) {
    return;
  }

  let marketsByLeague = {};

  function el(html) {
    const wrap = document.createElement("div");
    wrap.innerHTML = html.trim();
    return wrap.firstElementChild;
  }

  function leagueOptions() {
    return [
      ["nfl", "NFL"],
      ["cfb", "College Football"],
      ["nba", "NBA"],
      ["mlb", "MLB"],
      ["nhl", "NHL"],
    ].map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
  }

  function selectedOption(select) {
    return select.options[select.selectedIndex] || null;
  }

  function marketInfo(node) {
    const league = node.querySelector('[name="league"]').value;
    const key = node.querySelector('[name="market"]').value;
    const markets = marketsByLeague[league] || [];
    return markets.find((item) => item.key === key) || null;
  }

  function setHidden(label, hidden) {
    if (!label) {
      return;
    }
    label.hidden = hidden;
    const field = label.querySelector("input, select");
    if (field) {
      field.disabled = hidden;
      field.required = !hidden && Boolean(label.dataset.required);
    }
  }

  function addLeg() {
    const node = el(`
      <fieldset class="bet-leg-form">
        <legend>Leg</legend>
        <label>League
          <select name="league" required>
            <option value="">Select</option>
            ${leagueOptions()}
          </select>
        </label>
        <label>Game
          <select name="event_id" required>
            <option value="">Select a league first</option>
          </select>
        </label>
        <label>Market
          <select name="market" required>
            <option value="">Select a league first</option>
          </select>
        </label>
        <label>Outcome
          <select name="direction" required>
            <option value="">Select a market first</option>
          </select>
        </label>
        <label class="js-player-field" data-required="true" hidden>
          Player
          <select name="player_id">
            <option value="">Select a game first</option>
          </select>
        </label>
        <label class="js-line-field" data-required="true" hidden>
          Line
          <input name="line" type="text" inputmode="text" enterkeyhint="done" autocomplete="off" placeholder="+3.5 or 74.5">
        </label>
        <label>DK %
          <input name="odds_american" inputmode="decimal" placeholder="57.4">
          <span class="hint js-odds-converted"></span>
        </label>
        <button type="button" class="text-button remove-leg">Remove</button>
      </fieldset>
    `);
    legsRoot.appendChild(node);
    bindLeg(node);
    refreshLegCount();
    syncLegFields(node);
  }

  function refreshLegCount() {
    const kind = kindSelect.value;
    const count = legsRoot.querySelectorAll(".bet-leg-form").length;
    addButton.style.display = kind === "parlay" ? "inline-flex" : "none";
    const parlayOdds = document.getElementById("parlay-odds");
    const parlayLabel = document.getElementById("parlay-odds-field") || (parlayOdds && parlayOdds.closest("label"));
    if (parlayLabel) {
      parlayLabel.hidden = kind !== "parlay";
      if (parlayOdds) {
        parlayOdds.disabled = kind !== "parlay";
        if (kind !== "parlay") {
          parlayOdds.value = "";
        }
      }
    }
    if (kind === "single" && count > 1) {
      Array.from(legsRoot.querySelectorAll(".bet-leg-form")).slice(1).forEach((item) => item.remove());
    }
    if (count === 0) {
      addLeg();
    }
    updatePayout();
  }

  async function fetchJSON(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) {
      throw new Error("request failed");
    }
    return response.json();
  }

  function fillMarkets(node, markets) {
    const marketSelect = node.querySelector('[name="market"]');
    const player = (markets || []).filter((item) => item.scope === "player");
    const game = (markets || []).filter((item) => item.scope === "game");
    const option = (item) => `<option value="${item.key}" data-scope="${item.scope}">${item.label}</option>`;
    marketSelect.innerHTML =
      '<option value="">Select market</option>' +
      (player.length ? `<optgroup label="Player props">${player.map(option).join("")}</optgroup>` : "") +
      (game.length ? `<optgroup label="Game">${game.map(option).join("")}</optgroup>` : "");
  }

  function fillDirections(node) {
    const directionSelect = node.querySelector('[name="direction"]');
    const market = marketInfo(node);
    const eventSelect = node.querySelector('[name="event_id"]');
    const eventOption = selectedOption(eventSelect);
    const away = eventOption ? eventOption.getAttribute("data-away") : "";
    const home = eventOption ? eventOption.getAttribute("data-home") : "";
    if (!market) {
      directionSelect.innerHTML = '<option value="">Select a market first</option>';
      return;
    }
    const labels = {
      ml_away: away ? away + " ML" : "Away ML",
      ml_home: home ? home + " ML" : "Home ML",
      spread_away: away ? away + " spread" : "Away spread",
      spread_home: home ? home + " spread" : "Home spread",
      team_away_over: away ? away + " over" : "Away over",
      team_away_under: away ? away + " under" : "Away under",
      team_home_over: home ? home + " over" : "Home over",
      team_home_under: home ? home + " under" : "Home under",
      total_over: "Over",
      total_under: "Under",
      over: "Over",
      under: "Under",
    };
    directionSelect.innerHTML = (market.directions || []).map((item) => {
      return `<option value="${item.key}">${labels[item.key] || item.label}</option>`;
    }).join("");
  }

  function syncLegFields(node) {
    const market = marketInfo(node);
    const playerField = node.querySelector(".js-player-field");
    const lineField = node.querySelector(".js-line-field");
    const playerSelect = node.querySelector('[name="player_id"]');
    const lineInput = node.querySelector('[name="line"]');
    const isPlayer = Boolean(market && market.scope === "player");
    const needsLine = Boolean(market && market.key !== "moneyline");

    setHidden(playerField, !isPlayer);
    setHidden(lineField, !needsLine);

    if (!isPlayer && playerSelect) {
      playerSelect.value = "";
    }
    if (!needsLine && lineInput) {
      lineInput.value = "";
    }

    if (lineInput && market) {
      if (market.key === "spread") {
        lineInput.placeholder = "+3.5 or -7";
        lineInput.inputMode = "text";
      } else if (market.key === "total" || market.key === "team_total") {
        lineInput.placeholder = "47.5";
        lineInput.inputMode = "decimal";
      } else {
        lineInput.placeholder = "74.5";
        lineInput.inputMode = "decimal";
      }
    }

    fillDirections(node);
    if (isPlayer) {
      loadPlayers(node);
    }
  }

  function positionMatches(position, allowed) {
    if (!allowed || !allowed.length) {
      return true;
    }
    const tokens = String(position || "").toUpperCase().split(/[^A-Z0-9]+/).filter(Boolean);
    if (!tokens.length) {
      return true;
    }
    const allowedSet = new Set(allowed.map((item) => String(item).toUpperCase()));
    return tokens.some((token) => allowedSet.has(token));
  }

  function fillPlayerOptions(node, players) {
    const playerSelect = node.querySelector('[name="player_id"]');
    const market = marketInfo(node);
    const previous = playerSelect.value;
    const allowed = (market && market.positions) || [];
    const filtered = (players || []).filter((player) => positionMatches(player.position, allowed));
    if (!filtered.length) {
      playerSelect.innerHTML = '<option value="">No matching players</option>';
      return;
    }
    playerSelect.innerHTML = '<option value="">Select player</option>' + filtered.map((player) => {
      const pos = player.position ? " " + player.position : "";
      return `<option value="${player.id}" data-name="${player.name}" data-team="${player.team}">${player.name} · ${player.team}${pos}</option>`;
    }).join("");
    if (previous && Array.from(playerSelect.options).some((item) => item.value === previous)) {
      playerSelect.value = previous;
    }
  }

  async function loadPlayers(node) {
    const league = node.querySelector('[name="league"]').value;
    const eventId = node.querySelector('[name="event_id"]').value;
    const playerSelect = node.querySelector('[name="player_id"]');
    const market = marketInfo(node);
    if (!market || market.scope !== "player") {
      return;
    }
    if (!league || !eventId) {
      playerSelect.innerHTML = '<option value="">Select a game first</option>';
      return;
    }
    const cacheKey = league + ":" + eventId;
    if (node._playerCacheKey === cacheKey && Array.isArray(node._playerCache)) {
      fillPlayerOptions(node, node._playerCache);
      return;
    }
    playerSelect.innerHTML = '<option value="">Loading…</option>';
    try {
      const data = await fetchJSON(
        "/api/bets/players?league=" + encodeURIComponent(league) +
        "&event_id=" + encodeURIComponent(eventId)
      );
      node._playerCache = data.players || [];
      node._playerCacheKey = cacheKey;
      fillPlayerOptions(node, node._playerCache);
    } catch (error) {
      playerSelect.innerHTML = '<option value="">Could not load players</option>';
    }
  }

  async function bindLeg(node) {
    const league = node.querySelector('[name="league"]');
    const eventSelect = node.querySelector('[name="event_id"]');
    const marketSelect = node.querySelector('[name="market"]');
    node.querySelector(".remove-leg").addEventListener("click", () => {
      if (legsRoot.querySelectorAll(".bet-leg-form").length > 1) {
        node.remove();
        updatePayout();
      }
    });

    league.addEventListener("change", async () => {
      eventSelect.innerHTML = '<option value="">Loading…</option>';
      node.querySelector('[name="player_id"]').dataset.loaded = "";
      node._playerCache = null;
      node._playerCacheKey = "";
      try {
        const data = await fetchJSON("/api/bets/events?league=" + encodeURIComponent(league.value));
        eventSelect.innerHTML = '<option value="">Select game</option>' + data.events.map((event) => {
          return `<option value="${event.id}" data-away="${event.away}" data-home="${event.home}" data-label="${event.label}">${event.label} · ${event.status}</option>`;
        }).join("");
        const markets = await fetchJSON("/api/bets/markets?league=" + encodeURIComponent(league.value));
        marketsByLeague[league.value] = markets.markets;
        fillMarkets(node, markets.markets);
        syncLegFields(node);
      } catch (error) {
        eventSelect.innerHTML = '<option value="">Could not load games</option>';
      }
    });

    eventSelect.addEventListener("change", () => {
      node.querySelector('[name="player_id"]').dataset.loaded = "";
      node._playerCache = null;
      node._playerCacheKey = "";
      syncLegFields(node);
    });
    marketSelect.addEventListener("change", () => syncLegFields(node));
  }

  function parseAmerican(text) {
    const cleaned = String(text || "").replace(/[+\s,]/g, "");
    if (!cleaned) {
      return null;
    }
    const odds = parseInt(cleaned, 10);
    if (!odds || (odds > -100 && odds < 100)) {
      return null;
    }
    return odds;
  }

  function percentToAmerican(percent) {
    if (!Number.isFinite(percent) || percent <= 0 || percent >= 100) {
      return null;
    }
    const chance = percent / 100;
    if (Math.abs(chance - 0.5) < 1e-9) {
      return 100;
    }
    if (chance > 0.5) {
      return Math.round(-100 * chance / (1 - chance));
    }
    return Math.round(100 * (1 - chance) / chance);
  }

  function americanToPercent(odds) {
    if (odds < 0) {
      return 100 * Math.abs(odds) / (Math.abs(odds) + 100);
    }
    return 100 * 100 / (odds + 100);
  }

  function parseOdds(text) {
    const raw = String(text || "").trim();
    if (!raw) {
      return null;
    }
    if (/^[+-]/.test(raw)) {
      return parseAmerican(raw);
    }
    const marked = raw.includes("%");
    const number = parseFloat(raw.replace(/%/g, "").replace(/,/g, ""));
    if (!Number.isFinite(number)) {
      return null;
    }
    if (marked || (number > 0 && number < 100 && !Number.isInteger(number))) {
      return percentToAmerican(number);
    }
    if (number > 0 && number < 100) {
      return percentToAmerican(number);
    }
    return parseAmerican(raw);
  }

  function formatPercent(percent) {
    if (!Number.isFinite(percent)) {
      return "";
    }
    const rounded = Math.round(percent * 10) / 10;
    return String(rounded);
  }

  function convertedLabel(odds) {
    return odds === null ? "" : "= " + formatAmerican(odds);
  }

  function formatAmerican(odds) {
    return odds > 0 ? "+" + odds : String(odds);
  }

  function americanToDecimal(odds) {
    return odds > 0 ? 1 + odds / 100 : 1 + 100 / Math.abs(odds);
  }

  function decimalToAmerican(decimalOdds) {
    if (decimalOdds >= 2) {
      return Math.round((decimalOdds - 1) * 100);
    }
    return Math.round(-100 / (decimalOdds - 1));
  }

  function combineOdds(values) {
    if (!values.length) {
      return null;
    }
    let decimal = 1;
    values.forEach((odds) => {
      decimal *= americanToDecimal(odds);
    });
    return decimalToAmerican(decimal);
  }

  function money(amount) {
    return "$" + Math.abs(amount).toFixed(2);
  }

  function updatePayout() {
    const box = document.getElementById("bet-payout");
    const hint = document.getElementById("bet-payout-hint");
    const oddsOut = document.getElementById("bet-odds-out");
    const profitOut = document.getElementById("bet-profit-out");
    const payoutOut = document.getElementById("bet-payout-out");
    if (!box || !oddsOut) {
      return;
    }
    const kind = kindSelect.value;
    const stake = parseFloat(String(form.stake.value || "").replace(/[$,]/g, ""));
    const parlayOdds = document.getElementById("parlay-odds");
    const legFields = Array.from(legsRoot.querySelectorAll('.bet-leg-form [name="odds_american"]'));
    const legOdds = legFields.map((field) => parseOdds(field.value)).filter((value) => value !== null);
    let odds = null;
    let hintText = "";

    legFields.forEach((field) => {
      const converted = field.parentElement && field.parentElement.querySelector(".js-odds-converted");
      if (converted) {
        converted.textContent = convertedLabel(parseOdds(field.value));
      }
    });
    const parlayConverted = document.getElementById("parlay-odds-converted");
    if (kind === "parlay") {
      const combined = (legOdds.length >= 2 && legOdds.length === legFields.length)
        ? combineOdds(legOdds)
        : null;
      if (combined !== null && parlayOdds && document.activeElement !== parlayOdds) {
        parlayOdds.value = formatPercent(americanToPercent(combined));
      }
      odds = parseOdds(parlayOdds && parlayOdds.value) || combined;
      if (parlayConverted) {
        parlayConverted.textContent = convertedLabel(odds);
      }
      if (combined !== null) {
        hintText = "Enter the win % DraftKings shows. ScoreCast converts it to American odds. Parlay % is combined from the legs; edit it if your slip differs.";
      } else if (legFields.length >= 2 && legOdds.length < legFields.length) {
        hintText = "Enter the DK win % on every leg to calculate the parlay price.";
      }
    } else {
      odds = legOdds.length === 1 ? legOdds[0] : null;
      if (parlayConverted) {
        parlayConverted.textContent = "";
      }
    }

    const hasStake = Number.isFinite(stake) && stake > 0;
    if (odds === null && !hasStake) {
      box.hidden = true;
      if (hint) {
        hint.textContent = hintText;
      }
      return;
    }
    box.hidden = false;
    oddsOut.textContent = odds === null
      ? "—"
      : formatAmerican(odds) + " (" + formatPercent(americanToPercent(odds)) + "%)";
    if (odds !== null && hasStake) {
      const profit = odds > 0 ? stake * (odds / 100) : stake * (100 / Math.abs(odds));
      profitOut.textContent = money(profit);
      payoutOut.textContent = money(stake + profit);
    } else {
      profitOut.textContent = "—";
      payoutOut.textContent = "—";
      if (!hasStake && odds !== null) {
        hintText = hintText || "Add a stake to see to-win and payout.";
      }
    }
    if (hint) {
      hint.textContent = hintText;
    }
  }

  kindSelect.addEventListener("change", refreshLegCount);
  addButton.addEventListener("click", addLeg);
  addLeg();
  form.addEventListener("input", updatePayout);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const errorNode = document.getElementById("bet-form-error");
    errorNode.textContent = "";
    const legs = [];
    legsRoot.querySelectorAll(".bet-leg-form").forEach((node) => {
      const eventSelect = node.querySelector('[name="event_id"]');
      const option = selectedOption(eventSelect);
      const playerSelect = node.querySelector('[name="player_id"]');
      const playerOption = selectedOption(playerSelect);
      const market = marketInfo(node);
      const isPlayer = Boolean(market && market.scope === "player");
      const needsLine = Boolean(market && market.key !== "moneyline");
      legs.push({
        league: node.querySelector('[name="league"]').value,
        event_id: eventSelect.value,
        event_label: option ? option.getAttribute("data-label") : "",
        away_team: option ? option.getAttribute("data-away") : "",
        home_team: option ? option.getAttribute("data-home") : "",
        market: node.querySelector('[name="market"]').value,
        direction: node.querySelector('[name="direction"]').value,
        line: needsLine ? node.querySelector('[name="line"]').value : "",
        odds_american: parseOdds(node.querySelector('[name="odds_american"]').value),
        player_id: isPlayer ? playerSelect.value : "",
        player_name: isPlayer && playerOption ? playerOption.getAttribute("data-name") : "",
        team: isPlayer && playerOption ? playerOption.getAttribute("data-team") : "",
      });
    });
    const payload = {
      kind: kindSelect.value,
      sportsbook: form.sportsbook.value,
      stake: form.stake.value,
      odds_american: kindSelect.value === "parlay"
        ? parseOdds(form.odds_american.value)
        : (legs[0] ? legs[0].odds_american : ""),
      notes: form.notes.value,
      legs: kindSelect.value === "single" ? legs.slice(0, 1) : legs,
    };
    try {
      const response = await fetch("/api/bets", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!data.ok) {
        errorNode.textContent = data.error || "Could not save that bet.";
        return;
      }
      window.location.href = "/bets/" + data.id;
    } catch (error) {
      errorNode.textContent = "Could not save that bet.";
    }
  });
})();

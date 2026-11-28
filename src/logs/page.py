"""Error log page."""

from html import escape


def _when(entry):
    raw = str(entry.get("last_at") or entry.get("at") or "")
    if len(raw) >= 16:
        return f"{raw[5:7]}/{raw[8:10]} {raw[11:16]}"
    return raw


def _entry_card(entry):
    code = escape(entry.get("code") or "APP-CRASH")
    summary = escape(entry.get("summary") or "")
    detail = escape(entry.get("detail") or "")
    when = escape(_when(entry))
    count = int(entry.get("count") or 1)
    times = f"{count} times" if count > 1 else "1 time"
    technical = ""
    if detail:
        technical = f"""
        <details class="log-details">
            <summary>Technical details</summary>
            <pre class="log-detail">{detail}</pre>
        </details>
        """
    return f"""
    <article class="card log-entry">
        <div class="log-entry-top">
            <span class="log-code">{code}</span>
            <span class="log-when">{when} · {times}</span>
        </div>
        <p class="log-summary">{summary}</p>
        {technical}
    </article>
    """


def render_logs_page(styles, header, entries, report):
    if entries:
        body = "".join(_entry_card(entry) for entry in entries)
        actions = """
        <div class="log-actions">
            <button type="button" class="quiet-button" id="copy-log">Copy log</button>
            <form method="POST" action="/logs/clear">
                <button type="submit" class="quiet-button">Clear</button>
            </form>
        </div>
        """
    else:
        body = """
        <div class="card">
            <div class="card-title">No errors</div>
            <p class="hint">Nothing has failed since the log was last cleared.</p>
        </div>
        """
        actions = ""
    safe_report = escape(report)
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>GameLine Pro Logs</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    {styles}
</head>
<body>
    <div class="page">
        {header}
        <p class="hint log-intro">
            Each line is a code, what it means, and the technical detail.
            Copy the log and send it when a board needs help.
        </p>
        {actions}
        {body}
        <textarea id="log-report" class="log-report" readonly>{safe_report}</textarea>
    </div>
    <script>
    (function () {{
      var button = document.getElementById("copy-log");
      var report = document.getElementById("log-report");
      if (!button || !report) return;
      button.addEventListener("click", function () {{
        var text = report.value;
        function done() {{
          button.textContent = "Copied";
        }}
        if (navigator.clipboard && navigator.clipboard.writeText) {{
          navigator.clipboard.writeText(text).then(done, function () {{
            report.focus();
            report.select();
            document.execCommand("copy");
            done();
          }});
          return;
        }}
        report.focus();
        report.select();
        document.execCommand("copy");
        done();
      }});
    }})();
    </script>
</body>
</html>
    """

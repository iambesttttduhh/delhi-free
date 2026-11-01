#!/usr/bin/env python3
"""
Build one real page per event from events.json — static HTML, no framework,
no backend, no cost. Also writes a static .ics per event and a sitemap.

Usage:
  python3 build_event_pages.py events.json outdir [--asset-base ../../] [--canonical https://...]

Design rules carried from the site: cream paper, near-black ink, orange accent,
Anton for display, Space Grotesk for body, JetBrains Mono for labels, hairlines
instead of cards. Photographs are never cropped and carry no overlay.
"""
import argparse
import html
import json
import os
import re
from datetime import date, datetime, timedelta, timezone

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

ap = argparse.ArgumentParser()
ap.add_argument("events")
ap.add_argument("outdir")
ap.add_argument("--asset-base", default="../../")
ap.add_argument("--canonical", default="https://iambesttttduhh.github.io/delhi-free/")
ap.add_argument("--single", default="", help="emit only this slug, as a flat file")
args = ap.parse_args()

data = json.load(open(args.events, encoding="utf-8"))
events = data["events"]

# A weekly listing carries the date it was first listed. Roll it forward to the next
# occurrence at build time, or the page and its calendar file advertise a past evening.
DAY_NAMES = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6}
TODAY = date.today()
for _ev in events:
    rec = _ev.get("recurrence") or ""
    m = re.search(r"every\s+(\w+)", rec, re.I)
    if not m or m.group(1).lower() not in DAY_NAMES:
        continue
    target = DAY_NAMES[m.group(1).lower()]
    st = datetime.fromisoformat(_ev["start"])
    add = (target - TODAY.weekday()) % 7
    nxt = TODAY + timedelta(days=add)
    delta = (nxt - st.date()).days
    if delta > 0:
        _ev["start"] = (st + timedelta(days=delta)).isoformat()
        _ev["end"] = (datetime.fromisoformat(_ev["end"]) + timedelta(days=delta)).isoformat()
        _ev["recurrence_next"] = f"next on {nxt.strftime('%a %-d %b')}"


def esc(s):
    return html.escape(s or "", quote=True)


def parse_iso(s):
    if not s:
        return None
    return datetime.fromisoformat(s)


def date_line(ev):
    s = parse_iso(ev["start"])
    e = parse_iso(ev["end"])
    if ev["all_day"]:
        if e and (e.date() - s.date()).days > 1:
            return f"{DOW[s.weekday()]} {s.day} {MON[s.month-1]} – {DOW[e.weekday()]} {e.day} {MON[e.month-1]} {e.year}"
        return f"{DOW[s.weekday()]} {s.day} {MON[s.month-1]} {s.year}"
    t = s.strftime("%-I:%M %p").lower()
    if e and e.date() != s.date():
        return f"{DOW[s.weekday()]} {s.day} {MON[s.month-1]} {t} – {DOW[e.weekday()]} {e.day} {MON[e.month-1]} {e.year}"
    if e:
        return f"{DOW[s.weekday()]} {s.day} {MON[s.month-1]} {s.year} · {t} – {e.strftime('%-I:%M %p').lower()}"
    return f"{DOW[s.weekday()]} {s.day} {MON[s.month-1]} {s.year} · {t}"


def cost_line(ev):
    c = ev["cost"]
    if c["type"] == "free":
        return c["note"] or "Free entry."
    if c["type"] == "under_500":
        return c["note"] or "Under Rs.500 — confirm the ticket price with the venue."
    return "Entry price not recorded — check with the organiser."


def fold(line):
    """RFC 5545 caps a content line at 75 octets; longer lines fold with a leading space."""
    if len(line.encode("utf-8")) <= 75:
        return line
    out, cur, size = [], "", 0
    for ch in line:
        b = len(ch.encode("utf-8"))
        if size + b > 74:
            out.append(cur)
            cur, size = " " + ch, 1 + b
        else:
            cur += ch
            size += b
    out.append(cur)
    return "\r\n".join(out)



def gcal_url(ev):
    """A one-click Google Calendar entry, pre-filled. The visitor still confirms the save."""
    from urllib.parse import quote
    s = parse_iso(ev["start"]); e = parse_iso(ev["end"])
    if ev["all_day"]:
        end_excl = (e.date() if e else s.date()) + timedelta(days=1)
        dates = s.strftime("%Y%m%d") + "/" + end_excl.strftime("%Y%m%d")
        ctz = ""
    else:
        from datetime import timezone as _tz
        utc = _tz(timedelta(hours=5, minutes=30))
        dates = (s.replace(tzinfo=utc).astimezone(_tz.utc).strftime("%Y%m%dT%H%M%SZ") + "/" +
                 e.replace(tzinfo=utc).astimezone(_tz.utc).strftime("%Y%m%dT%H%M%SZ"))
        ctz = "&ctz=Asia%2FKolkata"
    body = ev["what_happens"] or ev["gist"] or ""
    if ev["links"]["source"]:
        body += ("\n\n" if body else "") + "Source: " + ev["links"]["source"]
    return ("https://calendar.google.com/calendar/render?action=TEMPLATE"
            "&text=" + quote(ev["title"]) +
            "&dates=" + dates +
            "&details=" + quote(body) +
            "&location=" + quote(ev["address"]) + ctz)


def ics(ev):
    s = parse_iso(ev["start"])
    e = parse_iso(ev["end"])
    pad = lambda n: f"{n:02d}"
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Delhi Free//Events//EN",
         "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-TIMEZONE:Asia/Kolkata",
         "BEGIN:VTIMEZONE", "TZID:Asia/Kolkata", "BEGIN:STANDARD",
         "DTSTART:19700101T000000", "TZOFFSETFROM:+0530", "TZOFFSETTO:+0530",
         "TZNAME:IST", "END:STANDARD", "END:VTIMEZONE",
         "BEGIN:VEVENT", f"UID:dfe-{ev['id']}-{s.strftime('%Y%m%d')}@delhi-free",
         f"DTSTAMP:{now}"]
    if ev["all_day"]:
        end_excl = (e.date() if e else s.date()) + timedelta(days=1)
        L.append(f"DTSTART;VALUE=DATE:{s.strftime('%Y%m%d')}")
        L.append(f"DTEND;VALUE=DATE:{end_excl.strftime('%Y%m%d')}")
    else:
        L.append(f"DTSTART;TZID=Asia/Kolkata:{s.strftime('%Y%m%dT%H%M%S')}")
        L.append(f"DTEND;TZID=Asia/Kolkata:{e.strftime('%Y%m%dT%H%M%S')}")
    txt = lambda t: (t or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    L.append("SUMMARY:" + txt(ev["title"]))
    L.append("LOCATION:" + txt(ev["address"]))
    body = date_line(ev)
    if ev["time_approximate"]:
        body += " (time approximate)"
    if ev["what_happens"]:
        body += "\\n\\n" + txt(ev["what_happens"])
    if ev["links"]["source"]:
        body += "\\n\\nSource: " + txt(ev["links"]["source"])
    L.append("DESCRIPTION:" + body)
    L += ["BEGIN:VALARM", "TRIGGER:-PT2H", "ACTION:DISPLAY",
          "DESCRIPTION:" + txt(ev["title"]) + " starts in 2 hours", "END:VALARM",
          "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(fold(x) for x in L) + "\r\n"


def jsonld(ev, url):
    s = parse_iso(ev["start"])
    e = parse_iso(ev["end"])
    cancelled = ev["verification"]["status"] == "cancelled"
    node = {
        "@context": "https://schema.org",
        "@type": "Event",
        "name": ev["title"],
        "startDate": ev["start"],
        "endDate": ev["end"] if ev["end"] else ev["start"],
        "eventStatus": "https://schema.org/EventCancelled" if cancelled else "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "url": url,
        "description": ev["description"] or ev["summary"] or "",
        "location": {
            "@type": "Place",
            "name": ev["venue"],
            "address": {"@type": "PostalAddress", "streetAddress": ev["address"],
                        "addressLocality": "New Delhi", "addressRegion": "Delhi",
                        "addressCountry": "IN"},
        },
        "organizer": {"@type": "Organization", "name": ev["venue"],
                      "url": ev["links"]["source"] or ""},
    }
    if ev["coordinates"]["lat"] is not None:
        node["location"]["geo"] = {"@type": "GeoCoordinates",
                                   "latitude": ev["coordinates"]["lat"],
                                   "longitude": ev["coordinates"]["lng"]}
    if ev["cost"]["type"] == "free":
        node["isAccessibleForFree"] = True
        node["offers"] = {"@type": "Offer", "price": "0", "priceCurrency": "INR",
                          "availability": "https://schema.org/InStock"}
    elif ev["cost"]["amount_inr"]:
        node["isAccessibleForFree"] = False
        node["offers"] = {"@type": "Offer", "price": str(ev["cost"]["amount_inr"]),
                          "priceCurrency": "INR"}
    else:
        node["isAccessibleForFree"] = False
    if ev["photo"]:
        node["image"] = args.canonical.rstrip("/") + "/" + ev["photo"]["src"]
    return json.dumps(node, ensure_ascii=False)


CSS = """
:root{--paper:#f2f0e9;--card:#fbfaf6;--ink:#0c0c0d;--ink2:#3a3935;--muted:#6b6a63;
--rule:#cdc9bb;--accent:#ff3b1f;--good:#3f7a24;--warn:#a86200;
--onsolid:#fff;--disp:"Anton",Impact,sans-serif;--body:"Space Grotesk",-apple-system,"Segoe UI",sans-serif;
--mono:"JetBrains Mono",ui-monospace,Menlo,monospace}
[data-theme="dark"]{--paper:#111110;--card:#161615;--ink:#f4f2ea;--ink2:#cfcdc4;
--muted:#9a978c;--rule:#34332f;--accent:#c8ff2e;--good:#a8e06a;--warn:#f0b23c;--onsolid:#0c0c0d}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#111110;--card:#161615;
--ink:#f4f2ea;--ink2:#cfcdc4;--muted:#9a978c;--rule:#34332f;--accent:#c8ff2e;--good:#a8e06a;
--warn:#f0b23c;--onsolid:#0c0c0d}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--body);
font-size:16px;line-height:1.6}
.wrap{max-width:820px;margin:0 auto;padding:0 20px 72px}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:16px;
padding:20px 0 14px;border-bottom:1.5px solid var(--ink);font-family:var(--mono);
font-size:10.5px;letter-spacing:.12em;text-transform:uppercase}
.top a{color:var(--ink);text-decoration:none;border-bottom:1px solid var(--accent)}
.top .row{display:flex;align-items:baseline;gap:14px}
.themebtn{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;background:transparent;color:var(--muted);border:1px solid var(--rule);padding:4px 9px;cursor:pointer}
.themebtn:hover{color:var(--ink);border-color:var(--ink)}
.themebtn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.top span{color:var(--muted)}
h1{font-family:var(--disp);font-size:clamp(32px,6vw,54px);line-height:.96;margin:22px 0 10px;
letter-spacing:-.01em}
.dateline{font-family:var(--mono);font-size:12px;letter-spacing:.06em;color:var(--accent);
margin:0 0 6px;text-transform:uppercase}
.lede{font-size:18px;color:var(--ink2);margin:0 0 22px;max-width:60ch}
figure{margin:0 0 8px}
figure img{display:block;width:100%;height:auto;border:1px solid var(--rule);background:var(--card)}
.facts{border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);margin:26px 0 8px}
.facts dl{display:grid;grid-template-columns:150px 1fr;gap:0;margin:0}
.facts dt,.facts dd{margin:0;padding:9px 0;border-bottom:.5px solid var(--rule);font-size:14px}
.facts dt{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
color:var(--muted);padding-top:11px}
.facts dd{color:var(--ink2)}
.facts dl>:nth-last-child(-n+2){border-bottom:0}
@media(max-width:600px){.facts dl{grid-template-columns:1fr}.facts dt{padding-bottom:0;border-bottom:0}}
h2{font-family:var(--disp);font-size:22px;margin:34px 0 6px;letter-spacing:.01em}
h2 em{font-style:normal;color:var(--accent)}
p{margin:0 0 14px;color:var(--ink2)}
ol.run{list-style:none;margin:0;padding:0;border-left:2px solid var(--rule)}
ol.run li{display:grid;grid-template-columns:110px 1fr;gap:14px;padding:7px 0 7px 14px;
font-size:14.5px;border-bottom:.5px solid var(--rule)}
ol.run li:last-child{border-bottom:0}
ol.run .rt{font-family:var(--mono);font-size:11px;color:var(--accent);letter-spacing:.04em;padding-top:2px}
.tags{display:flex;flex-wrap:wrap;gap:7px;margin:12px 0 0;padding:0;list-style:none}
.tags li{font-family:var(--mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;
border:1px solid var(--rule);padding:4px 8px;color:var(--muted)}
.actions{display:flex;flex-wrap:wrap;gap:10px;margin:30px 0 0}
.btn{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;
padding:10px 15px;border:1px solid var(--ink);color:var(--ink);text-decoration:none;background:var(--card)}
.btn:hover{background:var(--ink);color:var(--paper)}
.btn.solid{background:var(--accent);border-color:var(--accent);color:var(--onsolid)}

.endedbar{background:var(--ink);color:var(--paper);font-family:var(--mono);font-size:11px;
line-height:1.6;letter-spacing:.02em;padding:10px 14px;margin:0 0 4px}
.endedbar b{font-weight:700}
.endedbar a{color:var(--accent)}
.is-ended .actions .btn.solid{background:var(--rule);border-color:var(--rule);color:var(--ink2)}
.trust{margin-top:26px;padding-top:14px;border-top:1px solid var(--rule);
font-family:var(--mono);font-size:10.5px;letter-spacing:.04em;color:var(--muted)}
.trust b{color:var(--warn);font-weight:500}
footer{margin-top:40px;border-top:1.5px solid var(--ink);padding-top:12px;
font-family:var(--mono);font-size:10.5px;color:var(--muted);display:flex;flex-wrap:wrap;
gap:6px 20px;justify-content:space-between}
a{color:var(--ink)}
"""

FONTS = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Space+Grotesk:wght@400;500;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">"""


CSS_B = """
:root{--paper:#f2f0e9;--card:#fbfaf6;--ink:#0c0c0d;--ink2:#3a3935;--muted:#6b6a63;
--rule:#cdc9bb;--accent:#ff3b1f;--good:#3f7a24;--warn:#a86200;--onsolid:#fff;
--disp:"Anton",Impact,sans-serif;--body:"Space Grotesk",-apple-system,"Segoe UI",sans-serif;
--mono:"JetBrains Mono",ui-monospace,Menlo,monospace}
[data-theme="dark"]{--paper:#111110;--card:#161615;--ink:#f4f2ea;--ink2:#cfcdc4;
--muted:#9a978c;--rule:#34332f;--accent:#c8ff2e;--good:#a8e06a;--warn:#f0b23c;--onsolid:#0c0c0d}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#111110;--card:#161615;
--ink:#f4f2ea;--ink2:#cfcdc4;--muted:#9a978c;--rule:#34332f;--accent:#c8ff2e;--good:#a8e06a;
--warn:#f0b23c;--onsolid:#0c0c0d}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--body);font-size:16px;line-height:1.6}
.wrap{max-width:760px;margin:0 auto;padding:0 20px 72px}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:16px;
padding:18px 0 10px;font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.top a{color:var(--ink);text-decoration:none;border-bottom:1px solid var(--accent)}
.top .row{display:flex;align-items:baseline;gap:14px}
.themebtn{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;background:transparent;color:var(--muted);border:1px solid var(--rule);padding:4px 9px;cursor:pointer}
.themebtn:hover{color:var(--ink);border-color:var(--ink)}
.themebtn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
h1{font-family:var(--disp);font-size:clamp(36px,8vw,60px);line-height:.92;margin:14px 0 0;letter-spacing:-.015em}
.strip{display:flex;gap:0;border-top:1.5px solid var(--ink);border-bottom:1.5px solid var(--ink);margin:16px 0 0}
.strip div{flex:1;padding:10px 9px;border-right:1px solid var(--rule);min-width:0}
.strip div:last-child{border-right:0}
.strip b{display:block;font-family:var(--mono);font-size:8.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--muted);margin-bottom:2px}
.strip span{font-family:var(--mono);font-size:12px;color:var(--ink);display:block;overflow-wrap:break-word}
figure{margin:18px 0 0}
figure img{display:block;width:100%;height:auto;border:1px solid var(--rule);background:var(--card)}
.big{font-family:var(--disp);font-size:23px;line-height:1.12;color:var(--ink);margin:20px 0 10px;letter-spacing:.005em}
.lede{font-size:16.5px;color:var(--ink2);margin:0 0 18px}
.facts{border-top:1px solid var(--rule);margin:20px 0 0}
.facts dl{display:grid;grid-template-columns:132px 1fr;gap:0;margin:0}
.facts dt,.facts dd{margin:0;padding:9px 0;border-bottom:.5px solid var(--rule);font-size:14px}
.facts dt{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);padding-top:11px}
.facts dd{color:var(--ink2)}
.facts dl>:nth-last-child(-n+2){border-bottom:0}
@media (max-width:560px){.facts dl{grid-template-columns:1fr}.facts dt{padding-bottom:0;border-bottom:0}}
h2{font-family:var(--disp);font-size:21px;margin:32px 0 6px;letter-spacing:.01em}
p{margin:0 0 14px;color:var(--ink2)}
ol.run{list-style:none;margin:0;padding:0;border-left:2px solid var(--rule)}
ol.run li{display:grid;grid-template-columns:104px 1fr;gap:14px;padding:7px 0 7px 13px;font-size:14.5px;border-bottom:.5px solid var(--rule)}
ol.run li:last-child{border-bottom:0}
ol.run .rt{font-family:var(--mono);font-size:10.5px;color:var(--accent);padding-top:2px}
.tags{display:flex;flex-wrap:wrap;gap:7px;margin:14px 0 0;padding:0;list-style:none}
.tags li{font-family:var(--mono);font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;border:1px solid var(--rule);padding:4px 8px;color:var(--muted)}
.actions{display:flex;flex-wrap:wrap;gap:10px;margin:30px 0 0}
.btn{font-family:var(--mono);font-size:11px;letter-spacing:.07em;text-transform:uppercase;padding:11px 15px;
border:1.5px solid var(--ink);color:var(--ink);text-decoration:none;background:var(--card);display:inline-block}
.btn:hover{background:var(--ink);color:var(--paper)}
.btn.solid{background:var(--accent);border-color:var(--accent);color:var(--onsolid)}
.btn.solid:hover{background:var(--ink);border-color:var(--ink)}

.trust{margin-top:26px;padding-top:14px;border-top:1px solid var(--rule);font-family:var(--mono);
font-size:10.5px;letter-spacing:.03em;color:var(--muted)}
.trust b{color:var(--ink);font-weight:500}
footer{margin-top:40px;border-top:1.5px solid var(--ink);padding-top:12px;font-family:var(--mono);
font-size:10.5px;color:var(--muted);display:flex;flex-wrap:wrap;gap:6px 20px;justify-content:space-between}
a{color:var(--ink)}
"""

THEME_JS = """<script>
(function () {
  var KEY = 'dfe-theme';
  var root = document.documentElement;
  var btn = document.getElementById('themeBtn');
  if (!btn) return;
  function systemDark() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  function current() {
    return root.getAttribute('data-theme') || (systemDark() ? 'dark' : 'light');
  }
  function label() { btn.textContent = current() === 'dark' ? 'Light' : 'Dark'; }
  try { var saved = localStorage.getItem(KEY); if (saved) root.setAttribute('data-theme', saved); } catch (e) {}
  label();
  btn.addEventListener('click', function () {
    var next = current() === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem(KEY, next); } catch (e) {}
    label();
  });
})();
</script>
"""


RUN_JS = """<script>
(function () {
  /* if this page was built a while ago, the run may have ended since — say so
     without waiting for the next rebuild */
  var endEl = document.querySelector('[data-run-end]');
  if (!endEl) return;
  var end = endEl.getAttribute('data-run-end');
  if (!end) return;
  var today = new Date();
  var t = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  if (new Date(end + 'T23:59:59') < t) {
    var b = document.querySelector('.endedbar');
    if (b) b.hidden = false;
    document.body.classList.add('is-ended');
  }
})();
</script>
"""


def page(ev, asset, canonical_root, ics_href):
    """Design B: poster. Title, then dates / entry / time, then the photograph, then the detail."""
    url = canonical_root.rstrip("/") + "/events/" + ev["slug"] + "/"
    s = parse_iso(ev["start"]); e = parse_iso(ev["end"])

    photo = ""
    if ev["photo"] and ev["photo"]["src"]:
        photo = (f'<figure><img src="{asset}{esc(ev["photo"]["src"])}" '
                 f'alt="{esc(ev["title"])} — photograph" width="{esc(ev["photo"]["width"] or "")}" '
                 f'height="{esc(ev["photo"]["height"] or "")}" loading="eager" decoding="async"></figure>')

    # the three-number strip: dates, entry, time
    dates_short = (f"{s.day} {MON[s.month-1]} – {e.day} {MON[e.month-1]}" if e and e.date() != s.date()
                   else f"{s.day} {MON[s.month-1]} {s.year}")
    entry = {"free": "Free", "under_500": "Under Rs.500"}.get(ev["cost"]["type"], "Ticketed")
    if ev["all_day"]:
        hours = "All day"
    elif e and e.date() != s.date():
        # a run of days has one opening time, not a start and end across weeks
        hours = "Opens " + s.strftime("%-I%p").lower()
    elif e:
        hours = s.strftime("%-I:%M %p").lower() + " – " + e.strftime("%-I:%M %p").lower()
    else:
        hours = s.strftime("%-I:%M %p").lower()

    facts = [("When", date_line(ev) + (" · time approximate" if ev["time_approximate"] else "")),
             ("Where", esc(ev["address"]))]
    if ev["metro"]:
        facts.append(("Metro", esc(ev["metro"])))
    facts.append(("Entry", esc(cost_line(ev))))
    if ev["recurrence"]:
        facts.append(("Repeats", esc(ev["recurrence"])))
    if ev["neighbourhood"]:
        facts.append(("Neighbourhood", esc(ev["neighbourhood"].replace("Neighbourhood: ", ""))))
    fact_html = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in facts if v)

    run = ""
    if ev["run_of_show"]:
        run = ("<h2>Run of show</h2><ol class='run'>" + "".join(
            f"<li><span class='rt'>{esc(i['time'])}</span><span>{esc(i['what'])}</span></li>"
            for i in ev["run_of_show"]) + "</ol>")

    practical = ""
    if ev["practical"]:
        rows = "".join(
            f"<dt>{esc(k.replace('_', ' ').capitalize())}</dt><dd>{esc(v)}</dd>"
            for k, v in ev["practical"].items() if k != "entry")
        if rows:
            practical = f"<h2>Before you go</h2><div class='facts'><dl>{rows}</dl></div>"

    tags = ""
    if ev["categories"]:
        tags = "<ul class='tags'>" + "".join(f"<li>{esc(t)}</li>" for t in ev["categories"]) + "</ul>"

    src = ev["links"]["source"]
    src_btn = (f'<a class="btn" href="{esc(src)}" target="_blank" rel="noopener">Source listing</a>'
               if src else "")
    map_btn = (f'<a class="btn" href="{esc(ev["links"]["map"])}" target="_blank" rel="noopener">Open in Maps</a>'
               if ev["links"]["map"] else "")

    run_end = (ev["end"] or ev["start"] or "")[:10]
    ended = run_end < date.today().isoformat()
    status = ev["verification"]["status"]
    note = {
        "verified": "checked against the organiser",
        "needs_rechecking": "not yet re-checked against the organiser",
        "unconfirmed": "unconfirmed — treat the details as provisional",
        "expired": "this run has ended; the page stays as a record",
        "cancelled": "this event was cancelled",
    }.get(status, "")
    checked = ev["verification"]["last_checked"] or "unknown"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(ev['title'])} — Delhi, Free</title>
<meta name="description" content="{esc((ev['summary'] or ev['description'] or '')[:300])}">
<link rel="canonical" href="{esc(url)}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Delhi, Free">
<meta property="og:title" content="{esc(ev['title'])}">
<meta property="og:description" content="{esc(date_line(ev))} · {esc(ev['venue'])}">
{"<meta property='og:image' content='" + esc(canonical_root.rstrip('/') + '/' + ev['photo']['src']) + "'>" if ev['photo'] and ev['photo']['src'] else ""}
<meta name="twitter:card" content="summary_large_image">
{FONTS}
<script type="application/ld+json">{jsonld(ev, url)}</script>
<style>{CSS_B}</style>
</head>
<body>
<div class="wrap">
  <div class="endedbar" data-run-end="{esc(run_end)}"{'' if ended else ' hidden'}>
    <b>This run has ended</b> — it finished on {esc(run_end)}. The page stays up as a record; for what is on now, <a href="{asset}index.html">see the list</a>.
  </div>
  <div class="top">
    <a href="{asset}index.html">Delhi, Free</a>
    <span class="row"><span>One event</span>
      <button class="themebtn" id="themeBtn" type="button" aria-label="Switch between light and dark">Dark</button>
    </span>
  </div>
  <h1>{esc(ev['title'])}</h1>
  <div class="strip">
    <div><b>Dates</b><span>{esc(dates_short)}</span></div>
    <div><b>Entry</b><span>{esc(entry)}</span></div>
    <div><b>Time</b><span>{esc(hours)}</span></div>
  </div>
  {photo}
  {('<p class="big">' + esc(ev['gist']) + '</p>') if ev.get('gist') else ''}
  <p class="lede">{esc(ev['description'] or ev['summary'] or '')}</p>
  <div class="facts"><dl>{fact_html}</dl></div>
  {('<h2>What happens</h2><p>' + esc(ev['what_happens']) + '</p>') if ev['what_happens'] else ''}
  {run}
  {('<h2>Food</h2><p>' + esc(ev['food']) + '</p>') if ev['food'] else ''}
  {practical}
  {tags}
  <div class="actions">
    <a class="btn solid" href="{esc(gcal_url(ev))}" target="_blank" rel="noopener">Add to Google Calendar</a>
    <a class="btn" href="{esc(ics_href)}">Apple / Outlook (.ics)</a>
    {map_btn}
    {src_btn}
    <a class="btn" href="{asset}index.html">All 51 events</a>
  </div>
  <p class="trust">Listings change. Last checked <b>{esc(checked)}</b> · {esc(note)}{' · run ended ' + esc(run_end) if ended else ''}</p>
  <footer>
    <span>Delhi, Free — free culture across Delhi NCR</span>
    <span>Photographs are shown whole and uncredited by design</span>
  </footer>
</div>
{THEME_JS}
{RUN_JS}
</body>
</html>
"""


os.makedirs(os.path.dirname(args.outdir) or "." if args.single else args.outdir, exist_ok=True)
made = []
for ev in events:
    if args.single and ev["slug"] != args.single:
        continue
    if args.single:
        path = args.outdir
        ics_href = ev["slug"] + ".ics"
        html_out = page(ev, args.asset_base, args.canonical, ics_href)
        open(path, "w", encoding="utf-8").write(html_out)
        open(os.path.splitext(path)[0] + ".ics", "w", encoding="utf-8", newline="").write(ics(ev))
        made.append(path)
        break
    d = os.path.join(args.outdir, "events", ev["slug"])
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "index.html"), "w", encoding="utf-8").write(
        page(ev, args.asset_base, args.canonical, "event.ics"))
    open(os.path.join(d, "event.ics"), "w", encoding="utf-8", newline="").write(ics(ev))
    made.append(ev["slug"])

# sitemap + a plain index of every event
if not args.single:
    root = args.canonical.rstrip("/")
    urls = [f"{root}/"] + [f"{root}/events/{e['slug']}/" for e in events]
    today = date.today().isoformat()
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sm.append(f"<url><loc>{u}</loc><lastmod>{today}</lastmod>"
                  f"<changefreq>weekly</changefreq><priority>{'1.0' if u == root + '/' else '0.8'}</priority></url>")
    sm.append("</urlset>")
    open(os.path.join(args.outdir, "sitemap.xml"), "w", encoding="utf-8").write("\n".join(sm))

print(f"pages written: {len(made)}")
print("first:", made[0] if made else "-")

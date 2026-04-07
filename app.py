import streamlit as st
import requests
import json
import re
from datetime import date, timedelta
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────

WEBHOOK_URL = "https://hook.eu2.make.com/38aryc6wvmu0ncdfwefttmhnxpa2drjo"

COMPETITORS = [
    "Leasepath", "Odessa", "LTi Technology Solutions ASPIRE",
    "White Clarke Group Solifi", "Alfa Systems Alfa Financial Software",
    "Soft4Leasing", "NETSOL Technologies LeasePak NFS",
    "Cassiopae Sopra Banking", "Leasys Stellantis", "Quantech Software",
    "Linedata", "IDS Solifi", "AutoLease+", "CALMS",
    "LeaseTeam LTi ASPIRE", "Whip Around", "FleetMaster Sopra", "NaviTrans Leasing",
]

SYSTEM_PROMPT = """Jsi „Konkurenční špion" – specialista na monitoring konkurence produktů OneCore v leasingovém a finančním sektoru.
Úkol: Systematicky sleduj a analyzuj veřejně dostupné informace o konkurenci za poslední 7 dní.
Zdroje: webové stránky, firemní blogy, LinkedIn, tiskové zprávy, Microsoft AppSource.
Zaměření: leasingové a finanční systémy, ERP integrace (Dynamics 365 BC, SAP apod.).
Benchmark reference: OneCore (Seyfor) – Střední Evropa – Microsoft Marketplace.
Fallback: pokud nejsou dostupná nová data za 7 dní, rozšiř na 14 dní.
DŮLEŽITÉ: Výstup VŽDY vrať jako validní JSON bez jakéhokoliv textu mimo JSON. Bez komentářů, bez trailing commas, bez markdown backticks."""


def get_iso_week(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def build_user_prompt(period: str, date_str: str) -> str:
    companies = ", ".join(COMPETITORS)
    return f"""Proveď týdenní competitive intelligence report pro periodu {period} (datum: {date_str}).

Sledované společnosti: {companies}.

Vrať validní JSON v přesně této struktuře:
{{"period":"YYYY-WXX","competitors":[{{"entity":"","region":"","activities":[{{"date":"YYYY-MM-DD","activity_type":"","topic_tags":[],"title":"","summary":"","source_url":"","engagement":{{"likes":null,"comments":null,"shares":null}},"importance_score":1,"is_event":false,"event_name":""}}]}}],"market":[{{"date":"YYYY-MM-DD","category":"","topic_tags":[],"title":"","summary":"","source_url":"","region":""}}]}}

Pravidla: nevynechávej žádná pole, místo "N/A" použij null nebo "", validní JSON bez komentářů, importance_score 1–5, activity_type: blog|press_release|linkedin|product_update|event|partnership|pricing|other"""


# ── OpenAI call ───────────────────────────────────────────────────────────────

def run_intel(api_key: str, period: str, date_str: str, log) -> dict:
    client = OpenAI(api_key=api_key)
    user_prompt = build_user_prompt(period, date_str)

    log("🔍 Volám OpenAI API s web search nástrojem...")

    response = client.responses.create(
        model="gpt-4o",
        tools=[{"type": "web_search_preview"}],
        instructions=SYSTEM_PROMPT,
        input=user_prompt,
    )

    # Count web searches used
    search_calls = sum(1 for item in response.output if item.type == "web_search_call")
    log(f"🌐 Web search dokončen ({search_calls} dotazů). Parsuju JSON...")

    # Extract text output
    raw_text = ""
    for item in response.output:
        if item.type == "message":
            for block in item.content:
                if hasattr(block, "text"):
                    raw_text += block.text

    if not raw_text:
        raise ValueError("OpenAI nevrátilo žádný textový výstup.")

    cleaned = re.sub(r"```json|```", "", raw_text).strip()

    try:
        report = json.loads(cleaned)
    except json.JSONDecodeError as e1:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            report = json.loads(m.group(0))
        else:
            raise ValueError(f"JSON parse selhal: {e1}\n\nSurový výstup:\n{raw_text[:500]}")

    return report


# ── Webhook ───────────────────────────────────────────────────────────────────

def send_webhook(report: dict) -> tuple[bool, str]:
    try:
        r = requests.post(WEBHOOK_URL, json=report, timeout=10)
        if r.ok:
            return True, f"HTTP {r.status_code}"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except requests.RequestException as e:
        return False, str(e)


# ── UI helpers ────────────────────────────────────────────────────────────────

def score_color(s: int) -> str:
    if s >= 5: return "🔴"
    if s >= 4: return "🟠"
    if s >= 3: return "🔵"
    return "⚪"


def render_competitor(comp: dict):
    acts = comp.get("activities", [])
    if not acts:
        return
    max_score = max((a.get("importance_score", 1) for a in acts), default=1)
    dots = score_color(max_score) + "  " + " ".join(["●" if i < max_score else "○" for i in range(5)])

    with st.expander(f"**{comp['entity']}** — {comp.get('region','')}  |  {len(acts)} aktivit  {dots}"):
        for act in acts:
            st.markdown(f"**{act.get('title', '—')}**")
            cols = st.columns([2, 2, 3])
            cols[0].caption(f"📌 `{act.get('activity_type','')}`")
            cols[1].caption(f"📅 {act.get('date','')}")
            cols[2].caption(f"⭐ Skóre: {act.get('importance_score',1)}/5")
            if act.get("summary"):
                st.write(act["summary"])
            tags = act.get("topic_tags", [])
            if tags:
                st.write(" ".join([f"`{t}`" for t in tags]))
            if act.get("source_url"):
                st.markdown(f"[→ zdroj]({act['source_url']})")
            st.divider()


def render_market(trends: list):
    for t in trends:
        with st.expander(f"**{t.get('title','—')}** — {t.get('region','')}"):
            st.caption(f"📂 {t.get('category','')}  |  📅 {t.get('date','')}")
            if t.get("summary"):
                st.write(t["summary"])
            tags = t.get("topic_tags", [])
            if tags:
                st.write(" ".join([f"`{t}`" for t in tags]))
            if t.get("source_url"):
                st.markdown(f"[→ zdroj]({t['source_url']})")


# ── Main app ──────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="OneCore Competitive Intel",
        page_icon="🕵️",
        layout="wide",
    )

    st.title("🕵️ OneCore Competitive Intel")
    st.caption(f"Týdenní monitoring konkurence · Seyfor · {len(COMPETITORS)} sledovaných firem")

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Nastavení")

        api_key = st.text_input(
            "OpenAI API klíč",
            type="password",
            placeholder="sk-...",
            help="Váš OpenAI API klíč. Není nikde ukládán.",
        )

        today = date.today()
        report_date = st.date_input("Datum reportu", value=today)
        period = get_iso_week(report_date)
        st.caption(f"Perioda: **{period}**")

        send_wh = st.toggle("Odeslat na Make webhook", value=True)

        st.divider()
        st.caption("**Sledované firmy**")
        for c in COMPETITORS:
            st.caption(f"· {c}")

    # ── Main panel ────────────────────────────────────────────────────────────
    if not api_key:
        st.info("👈 Zadejte OpenAI API klíč v postranním panelu a klikněte na **Spustit špiona**.")
        return

    if st.button("🚀 Spustit špiona", type="primary", use_container_width=True):
        date_str = report_date.isoformat()
        logs = []
        log_placeholder = st.empty()

        def log(msg: str):
            logs.append(msg)
            log_placeholder.info("\n\n".join(logs))

        with st.spinner("Probíhá monitoring..."):
            try:
                report = run_intel(api_key, period, date_str, log)
            except Exception as e:
                st.error(f"❌ Chyba: {e}")
                return

        log_placeholder.empty()

        # Stats
        competitors_with_acts = [c for c in report.get("competitors", []) if c.get("activities")]
        total_acts = sum(len(c.get("activities", [])) for c in report.get("competitors", []))
        high_pri = sum(1 for c in report.get("competitors", []) for a in c.get("activities", []) if a.get("importance_score", 1) >= 4)
        market = report.get("market", [])

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Aktivní konkurenti", len(competitors_with_acts), f"z {len(COMPETITORS)}")
        col2.metric("Celkem aktivit", total_acts, "za 7 dní")
        col3.metric("Tržní trendy", len(market))
        col4.metric("Vysoká priorita", high_pri, "skóre 4–5")

        # Webhook
        if send_wh:
            with st.spinner("Odesílám na Make webhook..."):
                ok, msg = send_webhook(report)
            if ok:
                st.success(f"✅ Make webhook: report odeslán ({msg})")
            else:
                st.warning(f"⚠️ Webhook selhal: {msg}")

        # Download JSON
        st.download_button(
            label="⬇️ Stáhnout JSON report",
            data=json.dumps(report, indent=2, ensure_ascii=False),
            file_name=f"onecore-intel-{period}.json",
            mime="application/json",
        )

        st.divider()

        # Competitors
        st.subheader("Konkurenti")
        sorted_comps = sorted(
            competitors_with_acts,
            key=lambda c: max((a.get("importance_score", 1) for a in c.get("activities", [])), default=0),
            reverse=True,
        )
        for comp in sorted_comps:
            render_competitor(comp)

        # Market
        if market:
            st.subheader("Tržní trendy")
            render_market(market)


if __name__ == "__main__":
    main()

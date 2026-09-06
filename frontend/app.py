import os
import sys
from datetime import datetime

import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

import api_client as api  # noqa: E402

st.set_page_config(page_title="Freshness-Aware RAG", layout="wide")

BACKEND_KEY = "FIRECRAWL_API_KEY"  # informational: the backend holds the real key


def _fmt(ts) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(ts)


st.title("Competitor Watch")
st.caption("Freshness-aware RAG over scheduled competitor scrapes.")

if not api.health():
    st.error(f"Cannot reach backend at {api.API_URL}. Start it with `uvicorn app.main:app --reload`.")
    st.stop()

tab_sources, tab_query, tab_history = st.tabs(["Sources", "Ask", "Change History"])


# --------------------------------------------------------------------------- Sources
with tab_sources:
    st.subheader("Watched sources")
    sources = api.list_sources()

    if sources:
        for src in sources:
            col1, col2, col3, col4 = st.columns([2, 3, 2, 1])
            col1.write(src["name"])
            col2.write(src["url"])
            interval = src["interval_seconds"] or "default"
            col3.caption(f"every {interval}s · added {_fmt(src['created_at'])}")
            if col4.button("Run now", key=f"run_{src['id']}"):
                with st.spinner("Scraping…"):
                    result = api.run_source(src["id"])
                if result["status"] == "success":
                    st.success(
                        f"added {result['added']}, changed {result['changed']}, "
                        f"unchanged {result['unchanged']}"
                    )
                else:
                    st.error(f"Scrape failed: run #{result['run_id']}")
            if col1.button("Delete", key=f"del_{src['id']}"):
                api.delete_source(src["id"])
                st.rerun()
    else:
        st.info("No sources yet. Add your first competitor page below.")

    st.divider()
    with st.form("add_source", clear_on_submit=True):
        st.subheader("Add a competitor page")
        name = st.text_input("Name (e.g. Nestlé UK)", placeholder="Nestlé UK")
        url = st.text_input("URL", placeholder="https://www.nestle.co.uk/products")
        col_a, col_b = st.columns(2)
        interval = col_a.number_input(
            "Rescrape interval (seconds)", min_value=300, step=300, value=21600
        )
        submit = col_b.form_submit_button("Add & watch")
        if submit:
            if not name or not url:
                st.warning("Name and URL are required.")
            else:
                try:
                    api.create_source(name, url, int(interval))
                    st.success("Added.")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))


# ----------------------------------------------------------------------------- Query
with tab_query:
    st.subheader("Ask about the current state")
    q = st.text_input("Question", placeholder="What is Nestlé's current price for milk chocolate?")
    top_k = st.slider("Top-k chunks", min_value=1, max_value=10, value=5)
    if st.button("Search", type="primary"):
        if not q.strip():
            st.warning("Enter a question.")
        else:
            with st.spinner("Embedding + retrieving…"):
                try:
                    results = api.query(q, top_k)
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
                    results = []
            if not results:
                st.info("No relevant chunks found. Run a scrape first.")
            for r in results:
                with st.container(border=True):
                    st.markdown(f"**{r['source_name']}** · v{r['version_no']} · {_fmt(r['changed_at'])}")
                    st.write(r["content"])
                    st.caption(f"distance {r['distance']:.3f} · {r['url']}")


# -------------------------------------------------------------------------- History
with tab_history:
    st.subheader("Change history per source")
    if not sources:
        st.info("Add a source to see its history.")
    else:
        chosen = st.selectbox("Source", [s["name"] for s in sources], format_func=lambda n: n)
        source = next(s for s in sources if s["name"] == chosen)
        changes = api.history(source["id"])
        if not changes:
            st.info("No changes recorded yet.")
        for c in changes:
            with st.container(border=True):
                verb = "removed" if c["action"] == "removed" else "live"
                st.markdown(
                    f"**{verb}** · v{c['version_no']} · changed {_fmt(c['changed_at'])}"
                    + (f" · removed {_fmt(c['removed_at'])}" if c.get("removed_at") else "")
                )
                st.write(c["content"])

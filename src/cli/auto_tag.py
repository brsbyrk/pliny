"""
auto_tag.py — c-TF-IDF + KMeans auto-tagging system for Pliny.

Groups entries by topic using title-based clustering, then aggregates
the LLM-generated auto_tags from each cluster to produce representative
topic keywords per centroid.

Strategy
--------
- HashingVectorizer (stateless, no vocabulary) for KMeans clustering.
- After clustering, aggregate auto_tags of all cluster members and
  take most frequent as the centroid's representative tags.
- Centroids stored in HashingVectorizer space for fast cosine-similarity
  prediction.
"""

import json
import sys
import re
import sqlite3
from collections import Counter
import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.metrics import silhouette_score
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
from lib.paths import DB_PATH, CENTROIDS_PATH

# ---------------------------------------------------------------------------
# Stopwords
# ---------------------------------------------------------------------------
HTML_STOP_WORDS = {
    "alt", "caption", "class", "col", "div", "href", "img",
    "javascript", "jpg", "png", "script", "span", "src", "style", "width",
}
STOP_WORDS = ENGLISH_STOP_WORDS | HTML_STOP_WORDS  # union of both sets

# ---------------------------------------------------------------------------
# Vectorizer — used ONLY for KMeans clustering (memory efficient).
# Feature indices cannot be mapped back to words, so keyword extraction
# uses the raw text directly.
# ---------------------------------------------------------------------------
VECTORIZER = HashingVectorizer(
    n_features=5000,
    norm="l1",
    stop_words=list(STOP_WORDS),
    alternate_sign=False,
)

# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

TOKEN_RE=re.compile(r"\b[a-z]{2,}\b")


def _tokenize(text: str) -> list[str]:
    """Lowercase, extract 2+ char alpha tokens, filter stopwords."""
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOP_WORDS]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _fetch_entries():
    """Return list of (id, title, content, auto_tags) from the database."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, title, content, auto_tags FROM entries")
        rows = cur.fetchall()
    finally:
        conn.close()
    return rows


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def load_centroids() -> list[dict]:
    """Load centroids from JSON.  Returns empty list if file missing/corrupt."""
    if not CENTROIDS_PATH.exists():
        return []
    try:
        with open(CENTROIDS_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_centroids(centroids: list[dict]):
    """Persist centroids list to JSON (creates parent dirs)."""
    CENTROIDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CENTROIDS_PATH, "w") as f:
        json.dump(centroids, f, indent=2)


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-d vectors."""
    dot = np.dot(a, b)
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(dot / (na * nb))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def predict_tags(title: str, content: str | None = None) -> list[str]:
    """
    Predict tags for a new entry.

    Vectorizes the title with the same HashingVectorizer used during
    rebuild, then finds the nearest cluster centroid via cosine similarity.

    Parameters
    ----------
    title : str
        The title of the entry (primary signal).
    content : str, optional
        The body text (currently unused, kept for API compatibility).

    Returns
    -------
    list[str]
        Up to 3 tag keywords from the nearest cluster.
        Returns [] if no centroids have been built yet.
    """
    centroids = load_centroids()
    if not centroids:
        return []

    vec = VECTORIZER.transform([title])
    vec_dense = vec.toarray().ravel()

    best_tags: list[str] | None = None
    best_sim = -1.0

    for c in centroids:
        centroid = np.array(c["centroid"], dtype=np.float64)
        sim = _cosine_similarity(vec_dense, centroid)
        if sim > best_sim:
            best_sim = sim
            best_tags = c["tags"]

    return best_tags if best_tags is not None else []


def rebuild():
    """
    Re-cluster all entries from the database, aggregate the LLM-generated
    auto_tags per cluster as representative keywords, and persist centroids.
    """
    entries = _fetch_entries()
    if not entries:
        print("No entries found in database.", file=sys.stderr)
        return

    titles = [row[1] for row in entries]

    # ---- 0. Parse auto_tags for each entry ----
    all_entry_tags: list[list[str]] = []
    for row in entries:
        tags_str = row[3]  # auto_tags column
        try:
            parsed = json.loads(tags_str) if isinstance(tags_str, str) and tags_str else []
        except (json.JSONDecodeError, TypeError):
            parsed = []
        all_entry_tags.append(parsed)

    # ---- 1. Vectorize titles with HashingVectorizer (for KMeans) ----
    title_matrix = VECTORIZER.fit_transform(titles)

    # ---- 2. Determine optimal K via silhouette score ----
    n_samples = title_matrix.shape[0]
    min_k = 8
    max_k = min(25, n_samples - 1)

    if n_samples <= min_k:
        best_k = n_samples
        print(f"Only {n_samples} entries; using K={best_k} (no silhouette search).")
    else:
        best_k = min_k
        best_score = -1.0
        for k in range(min_k, max_k + 1):
            km = KMeans(n_clusters=k, random_state=42, n_init="auto")
            labels = km.fit_predict(title_matrix)
            if len(set(labels)) < 2:
                continue
            score = silhouette_score(title_matrix, labels, metric="cosine")
            print(f"  K={k:2d}  silhouette={score:.4f}")
            if score > best_score:
                best_score = score
                best_k = k

        print(f"Selected K={best_k} (silhouette={best_score:.4f})")

    # ---- 3. Final KMeans ----
    kmeans = KMeans(n_clusters=best_k, random_state=42, n_init="auto")
    cluster_labels = kmeans.fit_predict(title_matrix)
    centroids_raw = kmeans.cluster_centers_  # shape (K, n_features)

    # ---- 4. Aggregate auto_tags per cluster ----
    cluster_tag_counts: list[Counter] = [Counter() for _ in range(best_k)]
    for tags, label in zip(all_entry_tags, cluster_labels):
        if not tags:
            continue
        for tag in tags:
            cluster_tag_counts[label][tag.lower().strip()] += 1

    # For each cluster, take the top 3 most frequent auto_tags
    cluster_keywords: list[list[str]] = []
    for label in range(best_k):
        top_tags = [tag for tag, _ in cluster_tag_counts[label].most_common(3)]
        cluster_keywords.append(top_tags)

    # ---- 5. Build centroids output ----
    centroids_out: list[dict] = []
    for label_idx in range(best_k):
        centroids_out.append({
            "cluster_id": int(label_idx),
            "tags": cluster_keywords[label_idx],
            "centroid": centroids_raw[label_idx].tolist(),
        })

    # ---- 6. Persist ----
    save_centroids(centroids_out)
    print(f"Saved {len(centroids_out)} cluster centroids to {CENTROIDS_PATH}")
    for i, c in enumerate(centroids_out):
        tag_str = ", ".join(c["tags"])
        print(f"  Cluster {i}: [{tag_str}]")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--rebuild" in sys.argv:
        rebuild()
    else:
        print("Usage: python3 src/auto_tag.py --rebuild")
        sys.exit(1)

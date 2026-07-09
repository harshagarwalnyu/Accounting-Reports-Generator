#!/usr/bin/env bash
# Fully automated graphify --update pipeline.
# Run from project root: bash scripts/update_graph.sh
# Or from Windows: wsl.exe -d Ubuntu -- bash /home/bossman/projects/accounting-reports-generator/scripts/update_graph.sh
set -euo pipefail

PROJ="/home/bossman/projects/accounting-reports-generator"
OUT="$PROJ/graphify-out"
cd "$PROJ"

# ── Step 1: Resolve interpreter ──────────────────────────────────────────────
if [ -f "$OUT/.graphify_python" ]; then
    PY=$(cat "$OUT/.graphify_python")
else
    GRAPHIFY_BIN=$(which graphify 2>/dev/null || true)
    if [ -n "$GRAPHIFY_BIN" ]; then
        PY=$(head -1 "$GRAPHIFY_BIN" | tr -d '#!')
        case "$PY" in *[!a-zA-Z0-9/_.-]*) PY="python3" ;; esac
    else
        PY="python3"
    fi
    mkdir -p "$OUT"
    "$PY" -c "import sys; open('graphify-out/.graphify_python','w').write(sys.executable)"
fi

# Ensure graphify is installed
"$PY" -c "import graphify" 2>/dev/null || "$PY" -m pip install graphifyy -q --break-system-packages
echo "[graphify] Using interpreter: $PY"

# ── Step 2: Incremental detect ───────────────────────────────────────────────
echo "[graphify] Detecting changed files..."
"$PY" - << 'PYEOF'
import json
from graphify.detect import detect_incremental
from pathlib import Path

result = detect_incremental(Path('.'))
new_total = result.get('new_total', 0)
Path('graphify-out/.graphify_incremental.json').write_text(json.dumps(result))

if new_total == 0:
    print('[graphify] No files changed since last run. Nothing to update.')
    import sys; sys.exit(0)

nf = result.get('new_files', {})
summary = ', '.join(f"{cat}={len(files)}" for cat, files in nf.items() if files)
print(f'[graphify] {new_total} changed file(s): {summary}')

# Write detect.json from incremental data for downstream steps
detect = {
    'files': result['files'],
    'total_files': result['total_files'],
    'total_words': result['total_words'],
    'needs_graph': result['needs_graph'],
    'warning': result.get('warning', ''),
    'skipped_sensitive': result.get('skipped_sensitive', []),
}
Path('graphify-out/.graphify_detect.json').write_text(json.dumps(detect, indent=2))
PYEOF

# Exit cleanly if nothing to update
if [ ! -f "$OUT/.graphify_detect.json" ]; then
    exit 0
fi

# ── Check if code-only ────────────────────────────────────────────────────────
CODE_ONLY=$("$PY" - << 'PYEOF'
import json
from pathlib import Path
CODE_EXTS = {'.py','.ts','.js','.go','.rs','.java','.cpp','.c','.rb','.swift',
             '.kt','.cs','.scala','.php','.cc','.cxx','.hpp','.h','.kts','.lua',
             '.toc','.mjs','.cjs','.tsx','.jsx','.ps1'}
inc = json.loads(Path('graphify-out/.graphify_incremental.json').read_text())
all_changed = [f for files in inc.get('new_files', {}).values() for f in files]
code_only = all(Path(f).suffix.lower() in CODE_EXTS for f in all_changed)
print('true' if code_only else 'false')
PYEOF
)

if [ "$CODE_ONLY" = "true" ]; then
    echo "[graphify] Code-only changes - skipping semantic extraction (no LLM needed)"
fi

# ── Save old graph ────────────────────────────────────────────────────────────
if [ -f "$OUT/graph.json" ]; then
    cp "$OUT/graph.json" "$OUT/.graphify_old.json"
fi

# ── Step 3A: AST extraction ───────────────────────────────────────────────────
echo "[graphify] Running AST extraction..."
"$PY" - << 'PYEOF'
import json
from graphify.extract import collect_files, extract
from pathlib import Path

detect = json.loads(Path('graphify-out/.graphify_detect.json').read_text())
code_files = []
for f in detect.get('files', {}).get('code', []):
    p = Path(f)
    code_files.extend(collect_files(p) if p.is_dir() else [p])

if code_files:
    result = extract(code_files, cache_root=Path('.'))
    Path('graphify-out/.graphify_ast.json').write_text(json.dumps(result, indent=2))
    print(f'[graphify] AST: {len(result["nodes"])} nodes, {len(result["edges"])} edges')
else:
    Path('graphify-out/.graphify_ast.json').write_text(
        json.dumps({'nodes':[],'edges':[],'input_tokens':0,'output_tokens':0}))
    print('[graphify] No code files - skipping AST')
PYEOF

# ── Step 3B: Semantic extraction (skip if code-only) ─────────────────────────
if [ "$CODE_ONLY" = "false" ]; then
    echo "[graphify] Checking semantic cache..."
    "$PY" - << 'PYEOF'
import json
from graphify.cache import check_semantic_cache
from pathlib import Path

detect = json.loads(Path('graphify-out/.graphify_detect.json').read_text())
all_files = [f for files in detect['files'].values() for f in files]
cached_nodes, cached_edges, cached_hyperedges, uncached = check_semantic_cache(all_files)

if cached_nodes or cached_edges or cached_hyperedges:
    Path('graphify-out/.graphify_cached.json').write_text(
        json.dumps({'nodes': cached_nodes, 'edges': cached_edges, 'hyperedges': cached_hyperedges}))
Path('graphify-out/.graphify_uncached.txt').write_text('\n'.join(uncached))

hit = len(all_files) - len(uncached)
print(f'[graphify] Semantic cache: {hit} hits, {len(uncached)} need extraction')
if uncached:
    for f in uncached:
        print(f'  [uncached] {f}')
PYEOF

    # Merge what we have from cache into semantic.json (subagent step skipped in auto mode)
    # For truly uncached non-code files, use the cache from prior runs if available
    "$PY" - << 'PYEOF'
import json
from pathlib import Path

cached = (json.loads(Path('graphify-out/.graphify_cached.json').read_text())
          if Path('graphify-out/.graphify_cached.json').exists()
          else {'nodes':[],'edges':[],'hyperedges':[]})

# Include any chunk files from a prior manual run
import glob
new_nodes, new_edges, new_hyperedges = [], [], []
for chunk_file in sorted(glob.glob('graphify-out/.graphify_chunk_*.json')):
    try:
        chunk = json.loads(Path(chunk_file).read_text())
        new_nodes += chunk.get('nodes', [])
        new_edges += chunk.get('edges', [])
        new_hyperedges += chunk.get('hyperedges', [])
    except Exception:
        pass

all_nodes = cached['nodes'] + new_nodes
all_edges = cached['edges'] + new_edges
all_hyperedges = cached.get('hyperedges', []) + new_hyperedges
seen = set()
deduped = [n for n in all_nodes if n['id'] not in seen and not seen.add(n['id'])]

merged = {'nodes': deduped, 'edges': all_edges, 'hyperedges': all_hyperedges,
          'input_tokens': 0, 'output_tokens': 0}
Path('graphify-out/.graphify_semantic.json').write_text(json.dumps(merged, indent=2))
print(f'[graphify] Semantic: {len(deduped)} nodes, {len(all_edges)} edges')
PYEOF
else
    # Code-only: write empty semantic
    "$PY" -c "
import json
from pathlib import Path
empty = {'nodes':[],'edges':[],'hyperedges':[],'input_tokens':0,'output_tokens':0}
Path('graphify-out/.graphify_semantic.json').write_text(json.dumps(empty))
"
fi

# ── Step 3C: Merge AST + semantic ────────────────────────────────────────────
"$PY" - << 'PYEOF'
import json
from pathlib import Path

ast = json.loads(Path('graphify-out/.graphify_ast.json').read_text())
sem = json.loads(Path('graphify-out/.graphify_semantic.json').read_text())

seen = {n['id'] for n in ast['nodes']}
merged_nodes = list(ast['nodes'])
for n in sem['nodes']:
    if n['id'] not in seen:
        merged_nodes.append(n)
        seen.add(n['id'])

merged = {
    'nodes': merged_nodes,
    'edges': ast['edges'] + sem['edges'],
    'hyperedges': sem.get('hyperedges', []),
    'input_tokens': sem.get('input_tokens', 0),
    'output_tokens': sem.get('output_tokens', 0),
}
Path('graphify-out/.graphify_extract.json').write_text(json.dumps(merged, indent=2))
print(f'[graphify] Merged: {len(merged_nodes)} nodes, {len(merged["edges"])} edges')
PYEOF

# ── Update: merge with existing graph ────────────────────────────────────────
"$PY" - << 'PYEOF'
import json
import networkx as nx
from graphify.build import build_from_json
from networkx.readwrite import json_graph
from pathlib import Path

new_extraction = json.loads(Path('graphify-out/.graphify_extract.json').read_text())
G_new = build_from_json(new_extraction)

if Path('graphify-out/.graphify_old.json').exists():
    existing_data = json.loads(Path('graphify-out/.graphify_old.json').read_text())
    G_existing = json_graph.node_link_graph(existing_data, edges='links')

    incremental = json.loads(Path('graphify-out/.graphify_incremental.json').read_text())
    deleted = set(incremental.get('deleted_files', []))
    if deleted:
        to_remove = [n for n, d in G_existing.nodes(data=True) if d.get('source_file') in deleted]
        G_existing.remove_nodes_from(to_remove)
        print(f'[graphify] Pruned {len(to_remove)} nodes from {len(deleted)} deleted files')

    G_existing.update(G_new)
    print(f'[graphify] After merge: {G_existing.number_of_nodes()} nodes, {G_existing.number_of_edges()} edges')

    merged_out = {
        'nodes': [{'id': n, **d} for n, d in G_existing.nodes(data=True)],
        'edges': [{'source': u, 'target': v, **d} for u, v, d in G_existing.edges(data=True)],
        'hyperedges': new_extraction.get('hyperedges', []),
        'input_tokens': new_extraction.get('input_tokens', 0),
        'output_tokens': new_extraction.get('output_tokens', 0),
    }
    Path('graphify-out/.graphify_extract.json').write_text(json.dumps(merged_out))
else:
    print(f'[graphify] Fresh graph: {G_new.number_of_nodes()} nodes, {G_new.number_of_edges()} edges')
PYEOF

# ── Step 4: Build, cluster, analyze, generate report ─────────────────────────
echo "[graphify] Building graph and clustering..."
"$PY" - << 'PYEOF'
import json
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate
from graphify.export import to_json
from pathlib import Path

extraction = json.loads(Path('graphify-out/.graphify_extract.json').read_text())
detection  = json.loads(Path('graphify-out/.graphify_detect.json').read_text())

G = build_from_json(extraction)
if G.number_of_nodes() == 0:
    print('[graphify] ERROR: Graph is empty - extraction produced no nodes.')
    raise SystemExit(1)

communities = cluster(G)
cohesion = score_all(G, communities)
tokens = {'input': extraction.get('input_tokens', 0), 'output': extraction.get('output_tokens', 0)}
gods = god_nodes(G)
surprises = surprising_connections(G, communities)

# Auto-label communities from their top nodes
def auto_label(cid, members, G):
    labels_raw = [G.nodes[n].get('label', n) for n in members if n in G.nodes]
    # Filter out file-level nodes (long paths) and duplicates
    clean = []
    seen = set()
    for lb in labels_raw:
        key = lb.lower().strip()
        if key not in seen and len(lb) < 60 and '/' not in lb and '\\' not in lb:
            seen.add(key)
            clean.append(lb)
    if not clean:
        return f'Community {cid}'
    # Build label from top 2 distinct tokens
    top = clean[:2]
    label = ' / '.join(t.replace('()', '').strip() for t in top)
    return label[:40] if label else f'Community {cid}'

labels = {cid: auto_label(cid, members, G) for cid, members in communities.items()}

questions = suggest_questions(G, communities, labels)
report = generate(G, communities, cohesion, labels, gods, surprises, detection, tokens,
                  '/home/bossman/projects/accounting-reports-generator', suggested_questions=questions)
Path('graphify-out/GRAPH_REPORT.md').write_text(report)
to_json(G, communities, 'graphify-out/graph.json')

analysis = {
    'communities': {str(k): v for k, v in communities.items()},
    'cohesion': {str(k): v for k, v in cohesion.items()},
    'gods': gods,
    'surprises': surprises,
    'questions': questions,
}
Path('graphify-out/.graphify_analysis.json').write_text(json.dumps(analysis, indent=2))
Path('graphify-out/.graphify_labels.json').write_text(json.dumps({str(k): v for k, v in labels.items()}))

print(f'[graphify] Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, {len(communities)} communities')
print('[graphify] Top god nodes:')
for g in gods[:5]:
    print(f'  {g["label"]} - {g["degree"]} edges')
PYEOF

# ── Step 6: Generate HTML ─────────────────────────────────────────────────────
echo "[graphify] Generating HTML visualization..."
"$PY" - << 'PYEOF'
import json
from graphify.build import build_from_json
from graphify.export import to_html
from pathlib import Path

extraction = json.loads(Path('graphify-out/.graphify_extract.json').read_text())
analysis   = json.loads(Path('graphify-out/.graphify_analysis.json').read_text())
labels_raw = json.loads(Path('graphify-out/.graphify_labels.json').read_text())

G = build_from_json(extraction)
communities = {int(k): v for k, v in analysis['communities'].items()}
labels = {int(k): v for k, v in labels_raw.items()}

if G.number_of_nodes() <= 5000:
    to_html(G, communities, 'graphify-out/graph.html', community_labels=labels)
    print('[graphify] graph.html written')
else:
    print(f'[graphify] Graph too large ({G.number_of_nodes()} nodes) for HTML')
PYEOF

# ── Step 8: Benchmark (only if >5000 words) ───────────────────────────────────
TOTAL_WORDS=$("$PY" -c "
import json; from pathlib import Path
d = json.loads(Path('graphify-out/.graphify_detect.json').read_text())
print(d.get('total_words', 0))
")
if [ "$TOTAL_WORDS" -gt 5000 ] 2>/dev/null; then
    "$PY" - << 'PYEOF'
import json
from graphify.benchmark import run_benchmark, print_benchmark
from pathlib import Path

detection = json.loads(Path('graphify-out/.graphify_detect.json').read_text())
result = run_benchmark('graphify-out/graph.json', corpus_words=detection['total_words'])
print_benchmark(result)
PYEOF
fi

# ── Step 9: Save manifest, update cost, clean up ──────────────────────────────
"$PY" - << 'PYEOF'
import json
from pathlib import Path
from datetime import datetime, timezone
from graphify.detect import save_manifest

detect = json.loads(Path('graphify-out/.graphify_detect.json').read_text())
save_manifest(detect['files'])

extract = json.loads(Path('graphify-out/.graphify_extract.json').read_text())
input_tok = extract.get('input_tokens', 0)
output_tok = extract.get('output_tokens', 0)

cost_path = Path('graphify-out/cost.json')
cost = json.loads(cost_path.read_text()) if cost_path.exists() else \
       {'runs': [], 'total_input_tokens': 0, 'total_output_tokens': 0}
cost['runs'].append({'date': datetime.now(timezone.utc).isoformat(),
                     'input_tokens': input_tok, 'output_tokens': output_tok,
                     'files': detect.get('total_files', 0)})
cost['total_input_tokens'] += input_tok
cost['total_output_tokens'] += output_tok
cost_path.write_text(json.dumps(cost, indent=2))
print(f'[graphify] Cost this run: {input_tok} input, {output_tok} output tokens ({len(cost["runs"])} total runs)')
PYEOF

rm -f "$OUT/.graphify_detect.json" "$OUT/.graphify_extract.json" "$OUT/.graphify_ast.json" \
      "$OUT/.graphify_semantic.json" "$OUT/.graphify_analysis.json" "$OUT/.graphify_labels.json" \
      "$OUT/.graphify_old.json" "$OUT/.graphify_incremental.json" "$OUT/.graphify_chunk_"*.json \
      "$OUT/.graphify_cached.json" "$OUT/.graphify_uncached.txt" "$OUT/.graphify_semantic_new.json" \
      "$OUT/.needs_update" 2>/dev/null || true

echo ""
echo "[graphify] Done. Outputs in graphify-out/"
echo "  graph.html        - open in browser"
echo "  GRAPH_REPORT.md   - audit report"
echo "  graph.json        - raw graph data"

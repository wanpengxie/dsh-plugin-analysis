#!/usr/bin/env python3
"""Group DSH plugins that are the same code, from GitHub metadata alone.

Inputs (from ../../dsh-plugins/): plugins.jsonl (metadata + dsh field) and
fingerprints.jsonl (fork parent, HEAD commit, root tree, top-level entry ids).
Git object ids are content addresses: equal ids mean equal content.

Relations that put two repos in one group (strongest first):
  fork         - GitHub says one is a fork of the other
  identical    - same root tree: every file the same
  same_package - same package.json blob (same name, version, dsh declaration)
  mostly_same  - >= 80% of their significant top-level entries are the same
Informational only (reported, never merged): same_readme, same_name.

The representative of a group is its earliest-created repo (the original);
the others are copies. A group's tier comes from the most-starred member.
Writes lists/high-priority.csv, lists/zero-star.csv, lists/duplicates.csv,
lists/same-readme.csv, lists/same-name.csv and lists/stats.json.
"""
import collections, csv, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "..", "dsh-plugins"))
LISTS = os.path.normpath(os.path.join(HERE, "..", "lists"))

# Entries that say nothing about which plugin it is.
TRIVIAL = {"license", "license.md", "license.txt", ".gitignore", ".gitattributes", ".npmignore", ".editorconfig",
           ".prettierrc", ".prettierrc.json", ".eslintrc", ".eslintrc.json", ".eslintrc.js", "package-lock.json",
           "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "tsconfig.json", ".github", ".vscode", ".npmrc",
           "readme.md", "readme.zh-cn.md", "readme_en.md", "readme.en.md", "readme_zh.md", "changelog.md"}
COMMON_LIMIT = 30  # an entry id shared by more repos than this is boilerplate, not a sign of copying
MOSTLY = 0.8


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def main():
    plugins = {json.loads(l)["full_name"]: json.loads(l) for l in open(os.path.join(SRC, "plugins.jsonl"))}
    fps = {}
    for l in open(os.path.join(SRC, "fingerprints.jsonl")):
        f = json.loads(l)
        if not f.get("unreachable"):
            fps[f["full_name"]] = f
    names = [n for n in plugins if n in fps]
    missing = [n for n in plugins if n not in fps]

    uf = UF()
    why = {}  # (a, b) -> relation, for the duplicates list

    def link(a, b, rel):
        if a == b:
            return
        uf.union(a, b)
        key = tuple(sorted((a, b)))
        why.setdefault(key, rel)

    # fork
    for n in names:
        parent = fps[n].get("parent")
        if fps[n].get("is_fork") and parent in fps:
            link(parent, n, "fork")
    # identical tree, same package.json
    by_tree, by_pkg, by_readme = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for n in names:
        f = fps[n]
        if f.get("tree"):
            by_tree[f["tree"]].append(n)
        ent = {k.lower(): v for k, v in (f.get("entries") or {}).items()}
        if ent.get("package.json"):
            by_pkg[ent["package.json"]].append(n)
        if ent.get("readme.md"):
            by_readme[ent["readme.md"]].append(n)
    for group in by_tree.values():
        for n in group[1:]:
            link(group[0], n, "identical")
    for group in by_pkg.values():
        for n in group[1:]:
            link(group[0], n, "same_package")
    # mostly the same significant entries
    sig = {}
    count = collections.Counter()
    for n in names:
        ent = {k.lower(): v for k, v in (fps[n].get("entries") or {}).items() if k.lower() not in TRIVIAL}
        sig[n] = set(ent.values())
        count.update(sig[n])
    index = collections.defaultdict(list)
    for n in names:
        for oid in sig[n]:
            if count[oid] <= COMMON_LIMIT:
                index[oid].append(n)
    for n in names:
        mine = {o for o in sig[n] if count[o] <= COMMON_LIMIT}
        if not mine:
            continue
        cand = collections.Counter()
        for o in mine:
            for m in index[o]:
                if m != n:
                    cand[m] += 1
        for m, shared in cand.items():
            union = len(sig[n] | sig[m])
            if union and shared / union >= MOSTLY:
                link(n, m, "mostly_same")

    groups = collections.defaultdict(list)
    for n in names:
        groups[uf.find(n)].append(n)

    def created(n):
        return fps[n].get("created_at") or plugins[n].get("created_at") or ""

    reps, dup_rows = [], []
    for members in groups.values():
        members.sort(key=lambda n: (created(n), n))
        rep = members[0]
        top = max((plugins[m].get("stars") or 0) for m in members)
        reps.append((rep, members, top))
        for m in members[1:]:
            rel = why.get(tuple(sorted((rep, m))))
            if rel is None:  # joined through another member
                rels = [why[k] for k in why if m in k and uf.find(k[0]) == uf.find(rep)]
                rel = rels[0] if rels else "transitive"
            dup_rows.append({"copy": m, "representative": rep, "relation": rel,
                             "copy_stars": plugins[m].get("stars") or 0, "copy_created_at": created(m),
                             "representative_created_at": created(rep)})

    def tier(stars):
        return "A" if stars >= 10 else ("B" if stars >= 1 else "C")

    def row(rep, members, top, rank):
        p, f = plugins[rep], fps[rep]
        return {"rank": rank, "tier": tier(top), "repo": rep, "url": p["url"], "commit": f.get("head"),
                "stars": p.get("stars") or 0, "group_top_stars": top, "copies": len(members) - 1,
                "created_at": created(rep), "pushed_at": p.get("pushed_at"), "commits": f.get("commits"),
                "language": p.get("language"), "license": p.get("license"), "disk_kb": f.get("disk_kb"),
                "description": (p.get("description") or "").replace("\n", " ")[:300]}

    reps.sort(key=lambda r: (-r[2], r[0]))
    high = [r for r in reps if r[2] >= 1]
    zero = [r for r in reps if r[2] < 1]
    os.makedirs(LISTS, exist_ok=True)
    fields = ["rank", "tier", "repo", "url", "commit", "stars", "group_top_stars", "copies", "created_at", "pushed_at",
              "commits", "language", "license", "disk_kb", "description"]
    for path, rows in (("high-priority.csv", high), ("zero-star.csv", zero)):
        with open(os.path.join(LISTS, path), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for i, (rep, members, top) in enumerate(rows, 1):
                w.writerow(row(rep, members, top, i))
    with open(os.path.join(LISTS, "duplicates.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["copy", "representative", "relation", "copy_stars", "copy_created_at", "representative_created_at"])
        w.writeheader()
        for r in sorted(dup_rows, key=lambda r: (r["representative"], r["copy"])):
            w.writerow(r)
    # informational
    with open(os.path.join(LISTS, "same-readme.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["readme_oid", "repos", "count"])
        for oid, ns in sorted(by_readme.items(), key=lambda kv: -len(kv[1])):
            if len(ns) > 1:
                w.writerow([oid, " ".join(sorted(ns)), len(ns)])
    by_name = collections.defaultdict(list)
    for n in names:
        by_name[n.split("/", 1)[1].lower()].append(n)
    with open(os.path.join(LISTS, "same-name.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "repos", "count"])
        for nm, ns in sorted(by_name.items(), key=lambda kv: -len(kv[1])):
            if len(ns) > 1:
                w.writerow([nm, " ".join(sorted(ns)), len(ns)])

    rel_count = collections.Counter(r["relation"] for r in dup_rows)
    stats = {
        "plugins": len(plugins), "fingerprinted": len(names), "not_fingerprinted": len(missing),
        "groups": len(reps), "copies": len(dup_rows), "copies_by_relation": dict(rel_count),
        "high_priority": len(high), "tier_A": sum(1 for r in high if r[2] >= 10), "tier_B": sum(1 for r in high if r[2] < 10),
        "zero_star": len(zero),
        "largest_groups": [{"representative": r[0], "members": len(r[1])} for r in sorted(reps, key=lambda r: -len(r[1]))[:15]],
    }
    with open(os.path.join(LISTS, "stats.json"), "w") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

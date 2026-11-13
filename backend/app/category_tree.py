"""One logical category graph, keyed by preserved Marketplace internal/eMAG IDs.

Only category metadata is materialized (never parameter values). The graph is
built in O(V+E); no recursive SQL or per-ancestor database round trips are used.
"""

from collections import Counter, defaultdict


class CategoryTree:
    def __init__(self, rows, counts=None):
        self.rows = {r["id"]: dict(r) for r in rows}
        self.external = {r["emag_category_id"]: r["id"] for r in self.rows.values()}
        self.counts = counts or {}
        self.deleted = {
            id for id, r in self.rows.items() if "deleted" in r["name"].casefold()
        }
        self.selectable = {
            id
            for id, r in self.rows.items()
            if r["is_allowed"] == 1 and id not in self.deleted
        }
        self.parents = {
            id: self.external.get(r["parent_id"]) for id, r in self.rows.items()
        }
        self.cycles = []
        visited = set()
        for start in self.rows:
            chain, positions = [], {}
            node = start
            while node is not None and node not in visited and node not in positions:
                positions[node] = len(chain)
                chain.append(node)
                node = self.parents[node]
            if node in positions:
                self.cycles.append(chain[positions[node] :])
            visited.update(chain)
        self.cycle_nodes = {id for cycle in self.cycles for id in cycle}
        # A deterministic display root exposes cyclic components without asserting
        # a replacement relationship. The original parent ID remains in every DTO.
        self.cycle_breaks = {min(cycle) for cycle in self.cycles}
        self.navigation = set()
        for start in self.selectable:
            node = start
            while (
                node is not None
                and node not in self.navigation
                and node not in self.deleted
            ):
                self.navigation.add(node)
                node = self.parents[node]
        self.visible_all = set(self.rows) - self.deleted
        self._depths = {}
        for start in self.rows:
            chain = []
            node = start
            while node is not None and node not in self._depths:
                chain.append(node)
                node = None if node in self.cycle_breaks else self.parents[node]
            depth = self._depths.get(node, 0)
            for id in reversed(chain):
                depth += 1
                self._depths[id] = depth

    def visible(self, view):
        return self.navigation if view == "navigation" else self.visible_all

    def parent(self, id, view):
        parent = self.parents[id]
        return (
            parent
            if id not in self.cycle_breaks and parent in self.visible(view)
            else None
        )

    def path_ids(self, id, view):
        path = []
        while id is not None:
            path.append(id)
            id = self.parent(id, view)
        return list(reversed(path))

    def light(self, id):
        r = self.rows[id]
        return {
            "id": id,
            "emag_category_id": r["emag_category_id"],
            "name": r["name"],
            "reference_key": f"emag_marketplace:{r['emag_category_id']}",
            "selectable": id in self.selectable,
            "classification": "selectable" if id in self.selectable else "structural",
        }

    def item(self, id, view, children=None, include_path=True):
        r = self.rows[id]
        parent = self.parent(id, view)
        raw_parent = self.parents[id]
        path = self.path_ids(id, view) if include_path else []
        error = None
        if any(n in self.cycle_nodes for n in path):
            error = "cycle"
        elif r["parent_id"] not in (None, 0) and raw_parent is None:
            error = "missing_parent"
        elif raw_parent is not None and parent is None:
            error = "excluded_parent"
        # Detail/search also surface an error higher up the ancestor chain.
        if not error and path:
            root = self.rows[path[0]]
            if root["parent_id"] not in (None, 0):
                error = (
                    "missing_parent"
                    if self.parents[path[0]] is None
                    else "excluded_parent"
                )
        counts = self.counts.get(
            id, {"total": 0, "mandatory": 0, "optional": 0, "unknown": 0}
        )
        return {
            **{k: v for k, v in r.items() if k != "parent_id"},
            **self.light(id),
            "parent_emag_id": r["parent_id"],
            "parent_id": parent,
            "parent_name": self.rows[parent]["name"] if parent is not None else None,
            "missing_parent": r["parent_id"] not in (None, 0) and raw_parent is None,
            "hierarchy_error": error,
            "cycle_break": id in self.cycle_breaks,
            "in_navigation": id in self.navigation,
            "children_count": children.get(id, 0) if children is not None else None,
            "parameter_count": counts["total"],
            "mandatory_parameter_count": counts["mandatory"],
            "optional_parameter_count": counts["optional"],
            "unknown_parameter_count": counts["unknown"],
            "ancestors": [self.light(n) for n in path[:-1]],
            "path": [self.light(n) for n in path],
            "source": {
                "key": "emag_marketplace",
                "identity": "emag_category_id",
                "parameter_policy": "direct_only",
            },
        }

    def children_counts(self, view):
        return Counter(self.parent(id, view) for id in self.visible(view))

    def coverage(self):
        missing = Counter(
            r["parent_id"]
            for id, r in self.rows.items()
            if r["parent_id"] not in (None, 0) and self.parents[id] is None
        )
        original_depths = {}
        children = defaultdict(list)
        roots = []
        for id, r in self.rows.items():
            if r["parent_id"] in (None, 0):
                roots.append(id)
            elif self.parents[id] is not None:
                children[self.parents[id]].append(id)
        queue = [(id, 1) for id in roots]
        for id, depth in queue:
            if id in original_depths:
                continue
            original_depths[id] = depth
            queue.extend((child, depth + 1) for child in children[id])
        return {
            "reference_total": len(self.rows),
            "selectable_total": len(self.selectable),
            "navigation_total": len(self.navigation),
            "nondeleted_total": len(self.visible_all),
            "structural_total": len(self.navigation - self.selectable),
            "deleted_marker_total": len(self.deleted),
            "original_root_reachable": len(original_depths),
            "original_unreachable": len(self.rows) - len(original_depths),
            "max_depth": max(original_depths.values(), default=0),
            "depth_counts": dict(sorted(Counter(original_depths.values()).items())),
            "missing_parent_links": sum(missing.values()),
            "missing_parent_ids": dict(sorted(missing.items())),
            "cycle_components": [
                [self.rows[id]["emag_category_id"] for id in cycle]
                for cycle in self.cycles
            ],
            "categories_with_parameters": sum(
                1 for counts in self.counts.values() if counts["total"]
            ),
            "parameter_definition_total": sum(
                counts["total"] for counts in self.counts.values()
            ),
            "webshop_completeness": "unverified",
            "parameter_inheritance": "not_assumed",
            "source": "pinfo_db.emag_categories",
            "counts_are_runtime_observations": True,
        }

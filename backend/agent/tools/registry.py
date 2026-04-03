from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Iterable, Tuple, Type


_TOOL_PACKAGES: Tuple[str, ...] = (
    # Keep a roughly "conceptual" order so tool lists are stable for humans.
    "backend.agent.tools.knowledge",
    "backend.agent.tools.search",
    "backend.agent.tools.analysis",
    "backend.agent.tools.generation",
    "backend.agent.tools.utils",
)


# Preserve historical order (best-effort). New mixins discovered at runtime are appended deterministically.
_PREFERRED_MIXIN_ORDER: Tuple[str, ...] = (
    "KnowledgePointsToolsMixin",
    "WebSearchKnowledgeToolsMixin",
    "GithubSearchToolsMixin",
    "StackExchangeToolsMixin",
    "MediaWikiToolsMixin",
    "BrowseWebPagesToolsMixin",
    "WikipediaToolsMixin",
    "QuestionBankToolsMixin",
    "AggregationToolsMixin",
    "SourceSynthesisToolsMixin",
    "KnowledgeTypeDetectionToolsMixin",
    "StudyMaterialGenerationToolsMixin",
    "SelfCritiqueToolsMixin",
    "RefineDraftToolsMixin",
    "StudyArchiveToolsMixin",
    "ContentReviewToolsMixin",
    "ExportToolsMixin",
    "LatexToolsMixin",
    "DiagramToolsMixin",
    "DiagramPlanningToolsMixin",
    "PlotToolsMixin",
)


def _iter_submodules(package_name: str) -> Iterable[str]:
    try:
        pkg = importlib.import_module(package_name)
    except Exception:
        return []

    pkg_path = getattr(pkg, "__path__", None)
    if not pkg_path:
        return []

    out: list[str] = []
    for mod in pkgutil.walk_packages(pkg_path, prefix=pkg.__name__ + "."):
        if mod.ispkg:
            continue
        out.append(mod.name)
    return out


def _discover_tool_mixins() -> list[Type[object]]:
    mixins: list[Type[object]] = []
    for package_name in _TOOL_PACKAGES:
        for mod_name in _iter_submodules(package_name):
            try:
                module = importlib.import_module(mod_name)
            except Exception:
                # Optional dependencies may not be installed (or tools may not be intended for this env).
                continue

            for obj in module.__dict__.values():
                if not inspect.isclass(obj):
                    continue
                if obj.__module__ != mod_name:
                    continue
                if not str(obj.__name__ or "").endswith("ToolsMixin"):
                    continue
                mixins.append(obj)

    # Dedup by fully-qualified name to keep the result stable when aliases are present.
    out: list[Type[object]] = []
    seen: set[str] = set()
    for cls in mixins:
        key = f"{cls.__module__}.{cls.__name__}"
        if key in seen:
            continue
        seen.add(key)
        out.append(cls)
    return out


def _sort_tool_mixins(mixins: list[Type[object]]) -> Tuple[Type[object], ...]:
    preferred = {name: idx for idx, name in enumerate(_PREFERRED_MIXIN_ORDER)}

    def _key(cls: Type[object]) -> tuple:
        name = str(getattr(cls, "__name__", "") or "")
        idx = preferred.get(name)
        if idx is not None:
            return (0, idx)
        return (1, str(getattr(cls, "__module__", "") or ""), name)

    return tuple(sorted(mixins, key=_key))


TOOL_MIXINS: Tuple[Type[object], ...] = _sort_tool_mixins(_discover_tool_mixins())


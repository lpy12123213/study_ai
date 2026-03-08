from __future__ import annotations

from typing import Tuple, Type

from backend.agent.tools.aggregation import AggregationToolsMixin
from backend.agent.tools.browse_web_pages import BrowseWebPagesToolsMixin
from backend.agent.tools.content_review import ContentReviewToolsMixin
from backend.agent.tools.diagram_planning import DiagramPlanningToolsMixin
from backend.agent.tools.diagrams import DiagramToolsMixin
from backend.agent.tools.exports import ExportToolsMixin
from backend.agent.tools.github_search import GithubSearchToolsMixin
from backend.agent.tools.knowledge_points import KnowledgePointsToolsMixin
from backend.agent.tools.knowledge_type_detection import KnowledgeTypeDetectionToolsMixin
from backend.agent.tools.latex_export import LatexToolsMixin
from backend.agent.tools.mediawiki_search import MediaWikiToolsMixin
from backend.agent.tools.plots import PlotToolsMixin
from backend.agent.tools.question_bank import QuestionBankToolsMixin
from backend.agent.tools.refine_draft import RefineDraftToolsMixin
from backend.agent.tools.self_critique import SelfCritiqueToolsMixin
from backend.agent.tools.source_synthesis import SourceSynthesisToolsMixin
from backend.agent.tools.stackexchange_search import StackExchangeToolsMixin
from backend.agent.tools.study_archive import StudyArchiveToolsMixin
from backend.agent.tools.study_material_generation import StudyMaterialGenerationToolsMixin
from backend.agent.tools.web_search_knowledge import WebSearchKnowledgeToolsMixin
from backend.agent.tools.wikipedia_search import WikipediaToolsMixin

TOOL_MIXINS: Tuple[Type[object], ...] = (
    KnowledgePointsToolsMixin,
    WebSearchKnowledgeToolsMixin,
    GithubSearchToolsMixin,
    StackExchangeToolsMixin,
    MediaWikiToolsMixin,
    BrowseWebPagesToolsMixin,
    WikipediaToolsMixin,
    QuestionBankToolsMixin,
    AggregationToolsMixin,
    SourceSynthesisToolsMixin,
    KnowledgeTypeDetectionToolsMixin,
    StudyMaterialGenerationToolsMixin,
    SelfCritiqueToolsMixin,
    RefineDraftToolsMixin,
    StudyArchiveToolsMixin,
    ContentReviewToolsMixin,
    ExportToolsMixin,
    LatexToolsMixin,
    DiagramToolsMixin,
    DiagramPlanningToolsMixin,
    PlotToolsMixin,
)

from __future__ import annotations

from typing import Tuple, Type

from backend.agent.tools.analysis.content_review import ContentReviewToolsMixin
from backend.agent.tools.analysis.refine_draft import RefineDraftToolsMixin
from backend.agent.tools.analysis.self_critique import SelfCritiqueToolsMixin
from backend.agent.tools.analysis.source_synthesis import SourceSynthesisToolsMixin
from backend.agent.tools.generation.diagram_planning import DiagramPlanningToolsMixin
from backend.agent.tools.generation.diagrams import DiagramToolsMixin
from backend.agent.tools.generation.exports import ExportToolsMixin
from backend.agent.tools.generation.latex_export import LatexToolsMixin
from backend.agent.tools.generation.paper_compose import PaperComposeToolsMixin
from backend.agent.tools.generation.plots import PlotToolsMixin
from backend.agent.tools.knowledge.knowledge_points import KnowledgePointsToolsMixin
from backend.agent.tools.knowledge.knowledge_type_detection import KnowledgeTypeDetectionToolsMixin
from backend.agent.tools.knowledge.question_bank import QuestionBankToolsMixin
from backend.agent.tools.knowledge.study_archive import StudyArchiveToolsMixin
from backend.agent.tools.knowledge.study_material_generation import StudyMaterialGenerationToolsMixin
from backend.agent.tools.search.browse_web_pages import BrowseWebPagesToolsMixin
from backend.agent.tools.search.github_search import GithubSearchToolsMixin
from backend.agent.tools.search.mediawiki_search import MediaWikiToolsMixin
from backend.agent.tools.search.stackexchange_search import StackExchangeToolsMixin
from backend.agent.tools.search.web_search_knowledge import WebSearchKnowledgeToolsMixin
from backend.agent.tools.search.wikipedia_search import WikipediaToolsMixin
from backend.agent.tools.utils.aggregation import AggregationToolsMixin

# Keep the executor's method resolution order explicit and IDE-visible. New tool groups
# should be added here deliberately rather than being discovered by package reflection.
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
    PaperComposeToolsMixin,
    DiagramToolsMixin,
    DiagramPlanningToolsMixin,
    PlotToolsMixin,
)

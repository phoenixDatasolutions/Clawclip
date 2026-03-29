"""NexusAI Developer Skills — code review, PR management, CI/CD, deployment, logs, DB, API testing, QA, automation."""

from __future__ import annotations

from nexusai.skills.developer.api_testing import APITestingSkill
from nexusai.skills.developer.automation import AutomationSkill
from nexusai.skills.developer.ci_cd import CICDSkill
from nexusai.skills.developer.code_review import CodeReviewSkill
from nexusai.skills.developer.db_ops import DatabaseOpsSkill
from nexusai.skills.developer.deployment import DeploymentSkill
from nexusai.skills.developer.log_analysis import LogAnalysisSkill
from nexusai.skills.developer.pr_management import PRManagementSkill
from nexusai.skills.developer.qa import QASkill

__all__ = [
    "CodeReviewSkill",
    "PRManagementSkill",
    "CICDSkill",
    "DeploymentSkill",
    "LogAnalysisSkill",
    "DatabaseOpsSkill",
    "APITestingSkill",
    "QASkill",
    "AutomationSkill",
]

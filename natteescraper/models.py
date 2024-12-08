from datetime import datetime
from pydantic import BaseModel, HttpUrl
from typing import Literal, List, Dict, Optional
from bs4 import BeautifulSoup, Tag
from requests import Session

from .errors import ScrapingError
from .constants import DEFAULT_HALL_OF_FAME_URL, DEFAULT_TESTCASE_URL

Code = str

Language = Literal[
    "C",
    "C++",
    "Pascal",
    "Java",
    "Ruby",
    "Python",
    "Haskell",
    "Digital",
    "PHP",
    "Rust",
    "Go",
    "PostgreSQL",
]


# Define data models
class LoginPostData(BaseModel):
    """Represents the login data required to authenticate with the platform."""

    utf8: Literal["✓"]
    authenticity_token: Optional[str]
    login: str
    password: str
    commit: Literal["login"]


class TestCase(BaseModel):
    """Represents a test case with input and output code."""

    input: str
    output: str


class Submissions(BaseModel):
    user: str
    task_id: str
    score: float
    code: Code
    language: Language
    runtime: float
    memory: int
    graded: datetime


class HallOfFame(BaseModel):
    """Represents the hall of fame data for a specific language."""

    best_runtime: Code
    best_memory: Code
    shortest_code: Code
    first_solver: Code


class Task(BaseModel):
    """Represents a fully scraped task."""

    task_name: str
    task_nickname: str
    task_id: str
    pdf_url: HttpUrl
    hall_of_fame: Dict[Language, HallOfFame]
    test_cases: List[TestCase]


class PartialTask(BaseModel):
    """Represents a partially scraped task."""

    task_name: str
    task_nickname: str
    task_id: str
    pdf_url: HttpUrl

    def resolve(self, session: Session) -> Task:
        """
        Resolves the partial task into a full task by scraping additional details.
        :param session: Authenticated session object.
        :return: Fully resolved `Task` object.
        """
        return Task(
            task_name=self.task_name,
            task_nickname=self.task_nickname,
            task_id=self.task_id,
            pdf_url=self.pdf_url,
            hall_of_fame=self.__scrape_hall_of_fame(session),
            test_cases=self.__scrape_test_cases(session),
        )

    def __scrape_test_cases(self, session: Session) -> List[TestCase]:
        """Scrapes test cases for the task."""

        from .scraper import NatteeScraper

        return NatteeScraper._scrape_test_cases(session, self.task_id)

    def __scrape_hall_of_fame(self, session: Session) -> Dict[Language, HallOfFame]:
        """Scrapes hall of fame data for the task."""

        from .scraper import NatteeScraper

        return NatteeScraper._scrape_hall_of_fame(session, self.task_id)

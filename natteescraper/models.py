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


class HallOfFame(BaseModel):
    """Represents the hall of fame data for a specific language."""

    best_runtime: str
    best_memory: str
    shortest_code: str
    first_solver: str


class Task(BaseModel):
    """Represents a fully scraped task."""

    task_name: str
    task_nickname: str
    task_id: str
    pdf_url: HttpUrl
    hall_of_fame: Dict[str, HallOfFame]
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
        response = session.get(f"{DEFAULT_TESTCASE_URL}/{self.task_id}")
        soup = BeautifulSoup(response.text, "html.parser")
        textareas = soup.find_all("textarea")

        inputs, outputs = textareas[::2], textareas[1::2]
        return [
            TestCase(input=input_.text, output=output.text)
            for input_, output in zip(inputs, outputs)
        ]

    def __scrape_hall_of_fame(self, session: Session) -> Dict[str, HallOfFame]:
        """Scrapes hall of fame data for the task."""

        from .scraper import NatteeScraper

        response = session.get(f"{DEFAULT_HALL_OF_FAME_URL}/{self.task_id}")
        rows = (
            BeautifulSoup(response.text, "html.parser")
            .select("table.table-hover")[-1]
            .select("tbody tr")[1:]
        )

        fame: Dict[str, HallOfFame] = {}
        for row in rows:
            language = row.select_one("td")

            if not isinstance(language, Tag):
                raise ScrapingError("nono")

            language = language.get_text(strip=True)
            links = row.select("td a[href^='/submissions']")

            fame[language] = HallOfFame(
                best_runtime=NatteeScraper._scrape_submission(
                    session, links[0].get_text(strip=True).strip("()").removeprefix("#")
                ),
                best_memory=NatteeScraper._scrape_submission(
                    session, links[1].get_text(strip=True).strip("()").removeprefix("#")
                ),
                shortest_code=NatteeScraper._scrape_submission(
                    session, links[2].get_text(strip=True).strip("()").removeprefix("#")
                ),
                first_solver=NatteeScraper._scrape_submission(
                    session, links[3].get_text(strip=True).strip("()").removeprefix("#")
                ),
            )
        return fame

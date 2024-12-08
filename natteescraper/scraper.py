from typing import List, Optional, Dict, get_args
import re
from pydantic import HttpUrl, TypeAdapter
from bs4.element import Tag
from bs4 import BeautifulSoup
from requests import Response, Session
from .models import Language, LoginPostData, PartialTask, HallOfFame
from .constants import (
    DEFAULT_ROOT_URL,
    DEFAULT_LOGIN_URL,
    DEFAULT_SUBMISSION_URL,
    DEFAULT_HALL_OF_FAME_URL,
)
from .errors import ScrapingError, LoginError


class NatteeScraper:
    """A scraper class for extracting tasks from the Nattee platform."""

    def __init__(self, post_data: LoginPostData):
        """
        Initialize the scraper with login data.

        :param post_data: Login data required to authenticate with the site.
        """
        self.post_data = post_data
        self.session: Optional[Session] = None
        self.partial_tasks = self.__scrape_tasks(self.__setup_login())

    def get_partial_tasks(self) -> List[PartialTask]:
        """
        Retrieve the list of partially scraped tasks.

        :return: List of PartialTask objects.
        """
        return self.partial_tasks

    def get_session(self) -> Session:
        """
        Retrieve the current session object.

        :raises AssertionError: If the session is not valid.
        :return: The active Session object.
        """
        assert self.session, "Session is not currently valid."
        return self.session

    def clone_session(self) -> Session:
        """
        Create a new session connected to the same server,
        reusing the cookies and headers from the current session.

        :raises AssertionError: If the current session is not valid.
        :return: A new Session object.
        """
        assert self.session, "No active session to clone from."

        # Create a new session
        new_session = Session()

        # Transfer cookies from the existing session
        new_session.cookies.update(self.session.cookies)

        # Copy headers to the new session
        new_session.headers.update(self.session.headers)

        return new_session

    def get_submission(self, submission_id: str) -> str:
        """
        Retrieve the content of a submission by its ID.

        :param submission_id: The ID of the submission.
        :return: The content of the submission.
        """
        return self._scrape_submission(self.get_session(), submission_id)

    def get_hall_of_fame(self, submission_id: str) -> Dict[Language, HallOfFame]:
        return self._scrape_hall_of_fame(self.get_session(), submission_id)

    @staticmethod
    def _scrape_submission(session: Session, submission_id: str) -> str:
        """
        Scrape the content of a submission.

        :param session: Active session object for authenticated requests.
        :param submission_id: The ID of the submission.
        :raises ScrapingError: If no content is found in the <textarea> element.
        :return: The text content of the submission.
        """
        response = session.get(f"{DEFAULT_SUBMISSION_URL}/{submission_id}")
        matches = re.findall(r"<textarea.*>(.*)</textarea>", response.text, re.DOTALL)

        if len(matches) <= 0:
            raise ScrapingError(
                f"No content found in <textarea> for submission ID: {submission_id}"
            )

        return matches[0]

    def __scrape_tasks(self, response: Response) -> List[PartialTask]:
        """
        Scrape tasks from the authenticated response.

        :param response: Authenticated response containing the tasks table.
        :raises ScrapingError: If the main tasks table or body is not found.
        :return: List of PartialTask objects.
        """
        main_table = BeautifulSoup(response.text, "html.parser").find(
            "table", {"id": "main_table"}
        )
        if not isinstance(main_table, Tag):
            raise ScrapingError("Main tasks table not found.")

        table_body = main_table.find("tbody")
        if not isinstance(table_body, Tag):
            raise ScrapingError("Main table body not found.")

        tasks_id = self.__get_tasks_id(response)
        tasks: List[PartialTask] = []

        for row in [child for child in table_body.children if isinstance(child, Tag)]:
            try:
                tasks.append(self.__process_task_row(row, tasks_id))
            except (ValueError, TypeError) as e:
                print(f"Failed to process a task row: {e}")

        return tasks

    @staticmethod
    def _scrape_hall_of_fame(
        session: Session, task_id: str
    ) -> Dict[Language, HallOfFame]:
        """
        Scrape Hall of Fame data for a specific task.

        :param session: A requests.Session object used for making HTTP requests.
        :param task_id: The unique identifier of the task.
        :raises ScrapingError: If the webpage structure is unexpected or the language type is not registered.
        :return: A dictionary mapping programming languages to HallOfFame objects.
        """

        response = session.get(f"{DEFAULT_HALL_OF_FAME_URL}/{task_id}")
        rows = (
            BeautifulSoup(response.text, "html.parser")
            .select("table.table-hover")[-1]
            .select("tbody tr")[1:]
        )

        fame: Dict[Language, HallOfFame] = {}
        for row in rows:
            language = row.select_one("td")

            if not isinstance(language, Tag):
                raise ScrapingError(
                    "Expected a valid HTML tag for the language field but found an invalid structure."
                )

            language = language.get_text(strip=True)
            links = row.select("td a[href^='/submissions']")

            if language not in get_args(Language):
                raise ScrapingError(
                    f"The language '{language}' is not registered in the Language type. "
                    "Please update the Language enumeration to include this entry."
                )

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

    def __process_task_row(self, task_row: Tag, tasks_id: List[str]) -> PartialTask:
        """
        Process a single task row and extract task details.

        :param task_row: BeautifulSoup Tag representing a task row.
        :param tasks_id: List of task IDs from the dropdown selector.
        :raises ValueError: If the row contains an unexpected number of columns.
        :return: PartialTask object.
        """
        columns = [child for child in task_row.children if isinstance(child, Tag)]
        if len(columns) != 6:
            raise ValueError(f"Unexpected number of columns: {len(columns)}")

        # Extract task index
        index = self.__extract_index(columns[0])

        # Extract task details
        info_column = columns[1]
        task_name, task_nickname, pdf_url = self.__extract_task_info(info_column)

        return PartialTask(
            task_name=task_name,
            task_nickname=task_nickname,
            task_id=tasks_id[index],
            pdf_url=TypeAdapter(HttpUrl).validate_python(pdf_url),
        )

    @staticmethod
    def __get_tasks_id(response: Response) -> List[str]:
        """
        Extract task IDs from the problem ID selector.

        :param response: Authenticated response containing the selector.
        :raises ScrapingError: If the task ID selector is not found.
        :return: List of task IDs.
        """
        soup = BeautifulSoup(response.text, "html.parser")
        selector = soup.find("select", {"id": "submission_problem_id"})

        if not isinstance(selector, Tag):
            raise ScrapingError("Task ID selector not found.")

        return [
            child_value
            for child in selector.find_all("option")[1:]
            if isinstance(child, Tag)
            and (child_value := child.get("value"))
            and isinstance(child_value, str)
        ]

    def __setup_login(self) -> Response:
        """
        Perform login and return the authenticated response.

        :raises LoginError: If login fails.
        :return: Authenticated Response object.
        """
        self.session = Session()
        index_page = self.session.get(DEFAULT_ROOT_URL)

        token = self.__extract_authenticity_token(index_page.text)
        self.post_data.authenticity_token = token

        response = self.session.post(DEFAULT_LOGIN_URL, data=dict(self.post_data))
        if response.status_code != 200:
            raise LoginError("Login failed.")

        return response

    @staticmethod
    def __extract_authenticity_token(html: str) -> str:
        """
        Extract authenticity token from the HTML.

        :param html: HTML string of the page.
        :raises LoginError: If the authenticity token is not found.
        :return: Authenticity token string.
        """
        soup = BeautifulSoup(html, "html.parser")
        token_tag = soup.find("input", attrs={"name": "authenticity_token"})
        if (
            not isinstance(token_tag, Tag)
            or not (token := token_tag.get("value"))
            or not isinstance(token, str)
        ):
            raise LoginError("Authenticity token not found.")

        return token

    @staticmethod
    def __extract_index(index_column: Tag) -> int:
        """
        Extract task index from the index column.

        :param index_column: Tag containing the task index.
        :raises ValueError: If the index element is missing or invalid.
        :return: Zero-based task index.
        """
        index_div = index_column.find("div")
        if not isinstance(index_div, Tag) or not index_div.text.isdigit():
            raise ValueError("Task index element is missing or invalid.")
        return int(index_div.text) - 1

    @staticmethod
    def __extract_task_info(info_column: Tag) -> tuple[str, str, str]:
        """
        Extract task name, nickname, and PDF URL.

        :param info_column: Tag containing task details.
        :raises ValueError: If task name, nickname, or PDF URL is missing or invalid.
        :return: Tuple containing task name, nickname, and PDF URL.
        """
        name_tag = info_column.select_one(".font-monospace")
        nickname_tag = info_column.select_one("strong")
        pdf_link = info_column.select_one("a[href*='get_statement']")
        pdf_url = None

        if not (isinstance(name_tag, Tag) and isinstance(nickname_tag, Tag)):
            raise ValueError("Task name or nickname element is missing.")
        if (
            not (pdf_url := pdf_link.get("href")) if pdf_link else None
        ) or not isinstance(pdf_url, str):
            raise ValueError("PDF URL is missing or invalid.")

        return (
            name_tag.get_text(strip=True),
            nickname_tag.get_text(strip=True),
            f"{DEFAULT_ROOT_URL}/{pdf_url.lstrip('/')}",
        )

    def __del__(self):
        """
        Close the session when the scraper object is destroyed.
        """
        if self.session:
            self.session.close()
